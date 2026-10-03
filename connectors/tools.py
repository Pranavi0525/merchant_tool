"""The four read-only tools an agent can call. Each returns a small JSON-able dict."""
from datetime import datetime, timedelta, timezone

from .errors import ConnectorError
from .shaping import detail, summarize, WARNING

MAX_ITEMS = 20
STATUS_IN = {"open": 2, "pending": 3, "resolved": 4, "closed": 5}
PRIORITY_IN = {"low": 1, "medium": 2, "high": 3, "urgent": 4}


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def list_tickets(client, page=1, per_page=10, updated_within_days=None):
    """Browse tickets, newest first. Without updated_within_days Freshdesk returns only the last 30 days."""
    per_page = max(1, min(per_page, MAX_ITEMS))
    since = _iso(_now() - timedelta(days=updated_within_days)) if updated_within_days else None
    rows = client.list_tickets(page=page, per_page=per_page, updated_since=since)
    scope = f"updated in the last {updated_within_days} days" if since else "created in the last 30 days (Freshdesk default)"
    return {"tickets": [summarize(t) for t in rows], "page": page,
            "has_more": len(rows) == per_page, "scope": scope, "content_warning": WARNING}


def get_ticket(client, ticket_id, include_conversations=True):
    """Full detail for one ticket, with the last few messages."""
    return detail(client.get_ticket(ticket_id, include_conversations))


def search_tickets(client, status=None, priority=None, tag=None, created_after=None,
                   due_before=None, page=1):
    """Structured search (not free text). Dates are YYYY-MM-DD. Max 30 results per page."""
    terms = []
    if status:
        terms.append(f"status:{STATUS_IN[status]}")
    if priority:
        terms.append(f"priority:{PRIORITY_IN[priority]}")
    if tag:
        terms.append(f"tag:'{tag}'")
    if created_after:
        terms.append(f"created_at:>'{created_after}'")
    if due_before:
        terms.append(f"due_by:<'{due_before}'")
    if not terms:
        raise ConnectorError("Give at least one filter: status, priority, tag, created_after or due_before.")
    res = client.search_tickets(" AND ".join(terms), page=page)
    shown = [summarize(t) for t in res["results"]][:MAX_ITEMS]
    note = f"Showing {len(shown)} of {res['total']} matches." + (
        " Narrow the filters or request the next page." if res["total"] > len(shown) else "")
    return {"tickets": shown, "total": res["total"], "page": page, "note": note, "content_warning": WARNING}


def find_by_keyword(client, keyword, days=30, max_pages=5, limit=10):
    """Free-text search done inside the connector: scans recent tickets, so coverage is bounded."""
    since = _iso(_now() - timedelta(days=days))
    scanned, hits = 0, []
    for page in range(1, max_pages + 1):
        rows = client.list_tickets(page=page, per_page=100, updated_since=since)
        scanned += len(rows)
        kw = keyword.lower()
        hits += [t for t in rows if kw in (t["subject"] + " " + (t.get("description_text") or "")).lower()]
        if len(rows) < 100:
            break
    complete = scanned < max_pages * 100
    return {"tickets": [summarize(t) for t in hits[:limit]], "matches": len(hits),
            "coverage": f"Scanned {scanned} tickets updated in the last {days} days."
                        + ("" if complete else " Stopped at the page cap, so older matches may be missing."),
            "content_warning": WARNING}