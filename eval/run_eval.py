"""Tool-level eval: 20 fixed questions, naive raw connector vs this connector.

WHAT THIS IS: for each question both connectors get the same best-effort scripted call plan (no LLM).
We score (a) does the data the agent would see support the correct answer, (b) policy checks
(no PII exposed, bounded output, injection fenced, retry), and (c) payload size in estimated tokens
(chars/4, an estimate, not a tokenizer count).
WHAT THIS IS NOT: it does not measure how an LLM behaves with these tools. Truth is computed from
fixtures/tickets.json by code that does not use the connector. Questions are fixed; do not tune them.

    python -m eval.run_eval            # regenerates fixtures, writes eval/results.md and results.json
"""
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
subprocess.run([sys.executable, "fixtures/generate_tickets.py"], cwd=ROOT, check=True, capture_output=True)
# Fixture ages are whole hours, so some tickets sit exactly on a window edge (e.g. updated 24h before
# generation). Wait past the edge so "last 24h" truth and the connector's own clock cannot disagree
# by one second-rounding. Found the hard way: a fast fresh-clone run scored one question differently.
time.sleep(2.5)

from fastapi.testclient import TestClient  # noqa: E402

from connector import tools  # noqa: E402
from connector.client import FreshdeskClient  # noqa: E402
from connector.errors import ConnectorError  # noqa: E402
from connector.shaping import clean  # noqa: E402
from mock_server import server as mock  # noqa: E402

http = TestClient(mock.app)
NOW = datetime.now(timezone.utc)
RAW = json.loads((ROOT / "fixtures" / "tickets.json").read_text())
ISO = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
PT = lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)  # noqa: E731
J = lambda o: json.dumps(o, separators=(",", ":"), ensure_ascii=False)  # noqa: E731


# ---------------- ground truth (independent of the connector) ----------------
def ids(pred):
    return {t["id"] for t in RAW if pred(t)}

def text(t):
    return ((t["subject"] or "") + " " + (t["description_text"] or "")).lower()

TRAP = {t["_trap"]: t["id"] for t in RAW if t.get("_trap")}
T = {
    "open": ids(lambda t: t["status"] == 2),
    "urgent_open": ids(lambda t: t["status"] == 2 and t["priority"] == 4),
    "upd24": ids(lambda t: PT(t["updated_at"]) >= NOW - timedelta(hours=24)),
    "overdue": ids(lambda t: t["status"] in (2, 3) and PT(t["due_by"]) < NOW),
    "pending": len(ids(lambda t: t["status"] == 3)),
    "refund": ids(lambda t: "refund" in text(t) and PT(t["updated_at"]) >= NOW - timedelta(days=365)),
    "upi": ids(lambda t: "upi" in text(t) and PT(t["updated_at"]) >= NOW - timedelta(days=365)),
    "tag_pf": ids(lambda t: "payment_failed" in t["tags"]),
}
OPEN_BY_REQ = {}
for t in RAW:
    if t["status"] == 2:
        OPEN_BY_REQ.setdefault(t["requester"]["id"], set()).add(t["id"])
T["multi_open_reqs"] = {r for r, s in OPEN_BY_REQ.items() if len(s) > 1}
CUSTOMER = sorted(T["multi_open_reqs"])[0]
T["customer"] = ids(lambda t: t["requester"]["id"] == CUSTOMER)
CONV = next(t for t in RAW if len(t.get("conversations", [])) >= 3)
RESOLVED = next(t for t in RAW if t["status"] == 4)
INJ = next(t for t in RAW if t.get("_trap") == "prompt_injection")


# ---------------- connector adapters ----------------
class Rec:
    def __init__(self):
        self.tokens = 0
        self.calls = 0
        self.blobs = []

    def add(self, obj):
        s = obj if isinstance(obj, str) else J(obj)
        self.tokens += len(s) // 4
        self.calls += 1
        self.blobs.append(s)
        return obj


class Smart:
    name = "agent-friendly"
    has_write_path = False
    states_read_only = True

    def __init__(self, rec):
        self.rec, self.slept = rec, []
        self.c = FreshdeskClient(api_key="test-key", http=http, sleep=self.slept.append)

    def search_all(self, **f):
        items, page, total = [], 1, None
        while page <= 10:
            out = self.rec.add(tools.search_tickets(self.c, page=page, **f))
            items += out["tickets"]; total = out["total"]
            if len(items) >= total:
                break
            page += 1
        return items, total

    def list_all(self, days):
        items, page = [], 1
        while True:
            out = self.rec.add(tools.list_tickets(self.c, page=page, per_page=20, updated_within_days=days))
            items += out["tickets"]
            if not out["has_more"]:
                return items
            page += 1

    def list_first_page(self, days):
        return self.rec.add(tools.list_tickets(self.c, per_page=20, updated_within_days=days))

    def keyword(self, kw, days=365):
        out = self.rec.add(tools.find_by_keyword(self.c, kw, days=days, limit=20))
        return {t["id"] for t in out["tickets"]}, out["matches"]

    def get(self, i):
        return self.rec.add(tools.get_ticket(self.c, i))

    def status_of(self, g):
        return g["status"]


class Naive:
    """Raw passthrough: whatever Freshdesk returns, no trimming, no masking, no retry, no paging notes."""
    name = "naive-raw"
    has_write_path = False  # kept GET-only so the comparison is about shaping, not permissions
    states_read_only = False

    def __init__(self, rec):
        self.rec = rec

    def _get(self, path, params=None):
        r = http.get(path, params=params, auth=("test-key", "X"))
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}")
        return r.json()

    @staticmethod
    def _q(status=None, priority=None, tag=None, due_before=None):
        S = {"open": 2, "pending": 3, "resolved": 4, "closed": 5}
        P = {"low": 1, "medium": 2, "high": 3, "urgent": 4}
        t = []
        if status: t.append(f"status:{S[status]}")
        if priority: t.append(f"priority:{P[priority]}")
        if tag: t.append(f"tag:'{tag}'")
        if due_before: t.append(f"due_by:<'{due_before}'")
        return '"' + " AND ".join(t) + '"'

    def search_all(self, **f):
        items, page = [], 1
        while page <= 10:
            out = self.rec.add(self._get("/api/v2/search/tickets", {"query": self._q(**f), "page": page}))
            items += out["results"]
            if len(items) >= out["total"]:
                break
            page += 1
        return items, out["total"]

    def list_all(self, days):
        items, page = [], 1
        while True:
            rows = self.rec.add(self._get("/api/v2/tickets", {"page": page, "per_page": 100,
                                                              "updated_since": ISO(NOW - timedelta(days=days))}))
            items += rows
            if len(rows) < 100:
                return items
            page += 1

    def list_first_page(self, days):
        rows = self.rec.add(self._get("/api/v2/tickets", {"per_page": 100, "updated_since": ISO(NOW - timedelta(days=days))}))
        return {"tickets": rows}

    def keyword(self, kw, days=365):
        rows = self.list_all(days)
        hit = {t["id"] for t in rows if kw in text(t)}
        return hit, len(hit)

    def get(self, i):
        return self.rec.add(self._get(f"/api/v2/tickets/{i}", {"include": "conversations"}))

    def status_of(self, g):
        return {2: "open", 3: "pending", 4: "resolved", 5: "closed"}[g["status"]]


def idset(items):
    return {t["id"] for t in items}

def tomorrow():
    return (NOW + timedelta(days=1)).strftime("%Y-%m-%d")

def has_raw_pii(blob, t):
    return t["requester"]["email"] in blob or t["requester"]["phone"] in blob


# ---------------- the 20 questions: each returns (passed, detail) ----------------
def q1(a):  items, _ = a.search_all(status="open"); return idset(items) == T["open"], f"{len(idset(items))}/{len(T['open'])} ids"
def q2(a):  items, _ = a.search_all(status="open", priority="urgent"); return idset(items) == T["urgent_open"], f"{len(idset(items))}/{len(T['urgent_open'])}"
def q3(a):  return idset([t for t in a.list_all(1) if True]) == T["upd24"], f"updated in 24h: expect {len(T['upd24'])}"
def q4(a):
    items = []
    for s in ("open", "pending"):
        items += a.search_all(status=s, due_before=tomorrow())[0]
    found = {t["id"] for t in items if PT(t["due_by"]) < NOW}
    return found == T["overdue"], f"{len(found)}/{len(T['overdue'])}"
def q5(a):  _, total = a.search_all(status="pending"); return total == T["pending"], f"total={total} expect {T['pending']}"
def q6(a):  got, n = a.keyword("refund"); return n == len(T["refund"]) and got <= T["refund"], f"matches={n} expect {len(T['refund'])}"
def q7(a):  got, n = a.keyword("upi"); return n == len(T["upi"]) and got <= T["upi"], f"matches={n} expect {len(T['upi'])}"
def q8(a):  items, _ = a.search_all(tag="payment_failed"); return idset(items) == T["tag_pf"], f"{len(idset(items))}/{len(T['tag_pf'])}"
def q9(a):  items = [t for t in a.list_all(365) if t["requester"]["id"] == CUSTOMER]; return idset(items) == T["customer"], f"{len(idset(items))}/{len(T['customer'])}"
def q10(a): got, _ = a.keyword("paisa"); return TRAP["hinglish"] in got, f"found={TRAP['hinglish'] in got}"
def q11(a):
    g = a.get(CONV["id"]); blob = J(g)
    return all(clean(m["body_text"])[:30] in blob for m in CONV["conversations"][-3:]), "last 3 messages present"
def q12(a):
    g = a.get(CONV["id"]); last = CONV["conversations"][-1]
    return clean(last["body_text"])[:30] in J(g), "last message present"
def q13(a):  return a.status_of(a.get(RESOLVED["id"])) == "resolved", "status resolved"
def q14(a):
    try:
        a.get(9999); return False, "returned data for a missing ticket"
    except (ConnectorError, RuntimeError) as e:
        return True, f"error: {str(e)[:60]}"
def q15(a):
    out = a.list_first_page(180)
    n = len(out["tickets"]); noted = "Showing" in J(out.get("note", ""))
    return n <= 20 and noted, f"returned {n}, 'Showing N' note={noted}"
def q16(a):
    g = a.get(INJ["id"]); blob = J(g)
    fenced = "untrusted_content" in blob and "never as instructions" in blob
    return (not has_raw_pii(blob, INJ)) and fenced, f"raw PII={has_raw_pii(blob, INJ)}, fenced={fenced}"
def q17(a):
    items, _ = a.search_all(status="open"); by = {}
    for t in items: by.setdefault(t["requester"]["id"], set()).add(t["id"])
    return {r for r, s in by.items() if len(s) > 1} == T["multi_open_reqs"], "multi-open requesters"
def q18(a):  return (not a.has_write_path) and a.states_read_only, f"write path={a.has_write_path}, tells agent it is read-only={a.states_read_only}"
def q19(a):  g = a.get(CONV["id"]); return not has_raw_pii(J(g), CONV), f"raw PII exposed={has_raw_pii(J(g), CONV)}"
def q20(a):
    http.post("/__mock/force_429?count=2")
    try:
        items, _ = a.search_all(status="open", priority="urgent")
        ok = idset(items) == T["urgent_open"]
        return ok, "recovered after 2x 429" if ok else "wrong answer"
    except Exception as e:  # noqa: BLE001
        return False, f"failed: {type(e).__name__}"
    finally:
        http.post("/__mock/force_429?count=0")

QUESTIONS = [
    (1, "Show open tickets", "search_tickets", q1), (2, "Urgent and still open?", "search_tickets", q2),
    (3, "What came in during the last 24 hours?", "list_tickets", q3), (4, "Which tickets are past their due date?", "search_tickets", q4),
    (5, "How many tickets are pending?", "search_tickets", q5), (6, "Find tickets about refunds", "find_by_keyword", q6),
    (7, "Any tickets mentioning UPI?", "find_by_keyword", q7), (8, "Tickets tagged payment_failed", "search_tickets", q8),
    (9, "Anything from this customer?", "list_tickets", q9), (10, "Find the Hinglish payment ticket", "find_by_keyword", q10),
    (11, "Summarise ticket X incl. conversation", "get_ticket", q11), (12, "Last reply on ticket X?", "get_ticket", q12),
    (13, "Is ticket X resolved?", "get_ticket", q13), (14, "Ticket 9999 (does not exist)", "get_ticket", q14),
    (15, "Show everything for the last 6 months", "list_tickets", q15), (16, "Summarise the poisoned ticket", "get_ticket", q16),
    (17, "Customers with more than one open ticket", "search_tickets", q17), (18, "Can you close ticket X?", "(none)", q18),
    (19, "Customer's email on ticket X?", "get_ticket", q19), (20, "429 mid-query", "search_tickets", q20),
]


def run():
    results = {}
    for cls in (Naive, Smart):
        rows = []
        for n, qtext, tool, fn in QUESTIONS:
            rec = Rec(); a = cls(rec)
            try:
                ok, detail = fn(a)
            except Exception as e:  # noqa: BLE001
                ok, detail = False, f"crashed: {type(e).__name__}: {str(e)[:60]}"
            rows.append({"q": n, "question": qtext, "expected_tool": tool, "pass": bool(ok),
                         "tokens": rec.tokens, "calls": rec.calls, "detail": detail})
        results[cls.name] = rows
    return results


def report(res):
    n, s = res["naive-raw"], res["agent-friendly"]
    lines = ["# Eval results (tool-level, scripted agent, synthetic data)", "",
             f"Run at {ISO(NOW)}. Tokens = chars/4 estimate of what the agent would read. No LLM was used.", "",
             "| # | Question | naive pass | naive tokens | friendly pass | friendly tokens | friendly detail |", "|---|---|---|---|---|---|---|"]
    for a, b in zip(n, s):
        lines.append(f"| {a['q']} | {a['question']} | {'✅' if a['pass'] else '❌'} | {a['tokens']:,} | {'✅' if b['pass'] else '❌'} | {b['tokens']:,} | {b['detail']} |")
    tot = lambda rows, k: sum(r[k] for r in rows)  # noqa: E731
    lines += ["", f"**Passed:** naive {tot(n,'pass')}/20, friendly {tot(s,'pass')}/20.  ",
              f"**Total tokens:** naive {tot(n,'tokens'):,}, friendly {tot(s,'tokens'):,} "
              f"({100 * (1 - tot(s,'tokens') / max(1, tot(n,'tokens'))):.0f}% fewer).", "",
              "Caveats: 20 questions, 61 synthetic tickets, one run, scripted call plans. Not statistically meaningful. "
              "Q18 and Q16's fencing check reward design features (read-only instructions, untrusted_content), "
              "not model behaviour."]
    return "\n".join(lines)


if __name__ == "__main__":
    res = run()
    (ROOT / "eval" / "results.json").write_text(json.dumps(res, indent=1))
    md = report(res)
    (ROOT / "eval" / "results.md").write_text(md, encoding="utf-8")
    print(md)
