"""The four read-only tools an agent can call. Each returns a small JSON-able dict.

  list_tickets     browse tickets, newest first
  get_ticket       one ticket in detail with its latest public messages
  search_tickets   exact filters Freshdesk supports server-side (status, priority, tag, dates)
  find_by_keyword  free-text search done in the connector (Freshdesk's API has none), with an
                   explicit statement of how much was scanned
"""
import re
from datetime import datetime, timedelta, timezone

from .errors import InvalidInput
from .shaping import WARNING, detail, summarize

MAX_ITEMS = 20
STATUS_IN = {"open": 2, "pending": 3, "resolved": 4, "closed": 5}
PRIORITY_IN = {"low": 1, "medium": 2, "high": 3, "urgent": 4}
_TAG = re.compile(r"^[\w\- ]{1,50}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _page(page):
    if not isinstance(page, int) or page < 1:
        raise InvalidInput("page must be a whole number >= 1.")
    return page


def list_tickets(client, page=1, per_page=10, updated_within_days=None):
    """Browse tickets, newest first. Without updated_within_days Freshdesk returns only tickets
    created in the last 30 days."""
    page = _page(page)
    per_page = max(1, min(per_page, MAX_ITEMS))
    if updated_within_days is not None and not 1 <= updated_within_days <= 730:
        raise InvalidInput("updated_within_days must be between 1 and 730.")
    since = _iso(_now() - timedelta(days=updated_within_days)) if updated_within_days else None
    rows = client.list_tickets(page=page, per_page=per_page, updated_since=since)
    scope = (f"updated in the last {updated_within_days} days" if since
             else "created in the last 30 days (Freshdesk default)")
    has_more = len(rows) == per_page
    note = f"Showing {len(rows)} tickets ({scope}), page {page}." + (
        " More may exist: request the next page." if has_more else " End of results.")
    return {"tickets": [summarize(t) for t in rows], "page": page, "has_more": has_more,
            "note": note, "content_warning": WARNING}


def get_ticket(client, ticket_id, include_conversations=True):
    """Full detail for one ticket, with the last few public messages."""
    if not isinstance(ticket_id, int) or ticket_id < 1:
        raise InvalidInput("ticket_id must be a positive whole number.")
    return detail(client.get_ticket(ticket_id, include_conversations))


def search_tickets(client, status=None, priority=None, tag=None, created_after=None,
                   due_before=None, page=1):
    """Structured search (not free text), up to 30 per page. Dates are YYYY-MM-DD, compared by day only."""
    page = _page(page)
    terms = []
    if status:
        if status not in STATUS_IN:
            raise InvalidInput(f"status must be one of {sorted(STATUS_IN)}.")
        terms.append(f"status:{STATUS_IN[status]}")
    if priority:
        if priority not in PRIORITY_IN:
            raise InvalidInput(f"priority must be one of {sorted(PRIORITY_IN)}.")
        terms.append(f"priority:{PRIORITY_IN[priority]}")
    if tag:
        if not _TAG.match(tag):
            raise InvalidInput("tag may only contain letters, digits, spaces, '_' and '-' (max 50).")
        terms.append(f"tag:'{tag}'")
    for name, val, field, op in (("created_after", created_after, "created_at", ">"),
                                 ("due_before", due_before, "due_by", "<")):
        if val:
            if not _DATE.match(val):
                raise InvalidInput(f"{name} must look like 2026-10-03.")
            terms.append(f"{field}:{op}'{val}'")
    if not terms:
        raise InvalidInput("Give at least one filter: status, priority, tag, created_after or due_before.")
    res = client.search_tickets(" AND ".join(terms), page=page)
    # Freshdesk pages search results 30 at a time. Return the whole page: trimming it to 20
    # would silently skip results 21-30 of every page.
    shown = [summarize(t) for t in res["results"]]
    total = res["total"]
    seen_so_far = (page - 1) * 30 + len(res["results"])
    note = f"Showing {len(shown)} of {total} matches (page {page})."
    if seen_so_far < total:
        note += " Request the next page or narrow the filters."
    return {"tickets": shown, "total": total, "page": page, "note": note, "content_warning": WARNING}


def find_by_keyword(client, keyword, days=30, max_pages=5, limit=10):
    """Free-text search inside the connector: scans recent tickets, so coverage is bounded."""
    kw = (keyword or "").strip().lower()
    if not kw or len(kw) > 50:
        raise InvalidInput("keyword must be 1-50 characters.")
    if not 1 <= days <= 730:
        raise InvalidInput("days must be between 1 and 730.")
    max_pages = max(1, min(max_pages, 10))
    limit = max(1, min(limit, MAX_ITEMS))
    since = _iso(_now() - timedelta(days=days))
    scanned, hits, hit_cap = 0, [], False
    for page in range(1, max_pages + 1):
        rows = client.list_tickets(page=page, per_page=100, updated_since=since)
        scanned += len(rows)
        hits += [t for t in rows if kw in ((t.get("subject") or "") + " " +
                                           (t.get("description_text") or "")).lower()]
        if len(rows) < 100:
            break
        hit_cap = page == max_pages
    coverage = f"Scanned {scanned} tickets updated in the last {days} days."
    if hit_cap:
        coverage += " Stopped at the page cap, so older matches may be missing."
    return {"tickets": [summarize(t) for t in hits[:limit]], "matches": len(hits),
            "shown": min(len(hits), limit), "coverage": coverage, "content_warning": WARNING}
