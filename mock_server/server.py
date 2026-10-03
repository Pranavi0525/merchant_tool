"""Mock of the Freshdesk ticket API, backed by fixtures/tickets.json.

Run:  uvicorn mock_server.server:app --port 8000
Env:  MOCK_API_KEY      key the mock accepts (default: test-key)
      MOCK_429_EVERY=N  every Nth request returns 429 (default: off)
Test helper: POST /__mock/force_429?count=2 makes the next 2 requests return 429.

Behaviours copied from my understanding of Freshdesk. Verify against the
official docs before claiming parity:
  - HTTP Basic auth, API key as username
  - list: page / per_page (max 100), only last 30 days unless updated_since is set
  - search: structured fields only, max 30 results per page, max 10 pages
  - 429 responses carry a Retry-After header
"""
import base64
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

TICKETS = json.loads((Path(__file__).parent.parent / "fixtures" / "tickets.json").read_text())
API_KEY = os.getenv("MOCK_API_KEY", "test-key")
EVERY = int(os.getenv("MOCK_429_EVERY", "0"))
state = {"count": 0, "force_429": 0}

app = FastAPI(title="Mock Freshdesk")


def _public(t, with_conversations=False):
    out = {k: v for k, v in t.items() if not k.startswith("_") and k != "conversations"}
    if with_conversations:
        out["conversations"] = t.get("conversations", [])
    return out


@app.middleware("http")
async def gate(request: Request, call_next):
    if request.url.path.startswith("/__mock"):
        return await call_next(request)
    state["count"] += 1
    if state["force_429"] > 0 or (EVERY and state["count"] % EVERY == 0):
        state["force_429"] = max(0, state["force_429"] - 1)
        return JSONResponse({"code": "rate_limit_exceeded", "message": "Too many requests."},
                            status_code=429, headers={"Retry-After": "1"})
    auth = request.headers.get("authorization", "")
    try:
        user = base64.b64decode(auth.split(" ", 1)[1]).decode().split(":", 1)[0]
    except Exception:
        user = None
    if user != API_KEY:
        return JSONResponse({"code": "invalid_credentials",
                             "message": "You have to be logged in to perform this action."},
                            status_code=401)
    return await call_next(request)


@app.post("/__mock/force_429")
def force_429(count: int = 1):
    state["force_429"] = count
    return {"ok": True}


@app.get("/api/v2/tickets")
def list_tickets(page: int = 1, per_page: int = 30, updated_since: str | None = None):
    per_page = min(per_page, 100)
    rows = TICKETS
    if updated_since:
        rows = [t for t in rows if t["updated_at"] >= updated_since]
    else:  # Freshdesk default window
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = [t for t in rows if t["created_at"] >= cutoff]
    rows = sorted(rows, key=lambda t: t["created_at"], reverse=True)
    start = (page - 1) * per_page
    return [_public(t) for t in rows[start:start + per_page]]


@app.get("/api/v2/tickets/{ticket_id}")
def get_ticket(ticket_id: int, include: str = ""):
    for t in TICKETS:
        if t["id"] == ticket_id:
            return _public(t, with_conversations="conversations" in include)
    return JSONResponse({"code": "resource_not_found", "message": "Resource not found."},
                        status_code=404)


def _match(t, field, op, value):
    if field == "tag":
        return value in t["tags"]
    if field in ("status", "priority"):
        return t[field] == int(value)
    if field in ("created_at", "updated_at", "due_by"):
        v = t[field][:10]  # Freshdesk date queries are date-granular
        return v > value if op == ">" else v < value if op == "<" else v == value
    raise ValueError(field)


@app.get("/api/v2/search/tickets")
def search_tickets(query: str, page: int = 1):
    q = query.strip('"')
    terms = re.findall(r"(\w+):([<>]?)'?([\w\-]+)'?", q)
    if not terms:
        return JSONResponse({"code": "invalid_query", "message": "Could not parse query."},
                            status_code=400)
    if page > 10:
        return JSONResponse({"code": "invalid_page", "message": "Max 10 pages."}, status_code=400)
    try:
        rows = [t for t in TICKETS if all(_match(t, f, o, v) for f, o, v in terms)]
    except ValueError as e:
        return JSONResponse({"code": "invalid_field",
                             "message": f"Field {e} not searchable."}, status_code=400)
    start = (page - 1) * 30
    return {"results": [_public(t) for t in rows[start:start + 30]], "total": len(rows)}