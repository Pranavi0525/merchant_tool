# StitchNest helpdesk connector (read-only Freshdesk MCP server)

**The story.** StitchNest is a fictional Indian D2C apparel brand that takes payments through Razorpay.
Its support lead can't tell which tickets are urgent, which are about payments ("money debited, order not
confirmed", refunds, failed UPI), and which are about to breach SLA. This connector lets an AI agent answer
those questions from the ticket data, safely: read-only, bounded output, customer PII masked, customer text
treated as untrusted.

Everything runs **with no credentials** against a local mock that imitates Freshdesk, using fictional data.

## Run it in 2 minutes

    python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    python fixtures/generate_tickets.py                     # dates are relative to "now"
    uvicorn mock_server.server:app --port 8000              # terminal 1: mock Freshdesk
    FRESHDESK_API_KEY=test-key python -m connector.mcp_server   # terminal 2: MCP server on stdio
    pytest -q                                               # 20 tests (spawns its own mock + stdio client)
    python -m eval.run_eval                                 # 20-question eval -> eval/results.md

Claude Desktop / any MCP client config (stdio):

    {"mcpServers": {"freshdesk": {"command": "python", "args": ["-m", "connector.mcp_server"],
      "cwd": "/path/to/stitchnest-connector",
      "env": {"FRESHDESK_API_KEY": "test-key", "FRESHDESK_BASE_URL": "http://127.0.0.1:8000"}}}}

**Real Freshdesk:** set `FRESHDESK_DOMAIN` (e.g. `acme` or `acme.freshdesk.com`) and `FRESHDESK_API_KEY`
(Profile settings -> API key). Auth is HTTP Basic with the key as username. The key is only sent over HTTPS
(localhost exempt). A wrong key gives: "Freshdesk rejected the API key (401). Check FRESHDESK_API_KEY."

## Tool specification (what the agent sees)

| Tool | Use it for | Notes |
|---|---|---|
| `list_tickets(page, per_page<=20, updated_within_days)` | Browse newest first | Freshdesk only returns the last 30 days unless `updated_within_days` is set; the response says which scope applied |
| `get_ticket(ticket_id)` | One ticket in detail | Masked email, description (truncated at 1,200 chars), last 5 public messages |
| `search_tickets(status, priority, tag, created_after, due_before, page)` | Exact filters and counts | `total` is exact; 30 per page; dates are day-granular |
| `find_by_keyword(keyword, days, limit)` | Free-text words | Freshdesk's API has no free-text search, so the connector scans recent tickets and reports `Scanned N ... Stopped at the page cap` when coverage is partial. Exact substring only: no synonyms, no translation |

All four are annotated `readOnlyHint`. Responses are compact JSON (indentation costs tokens) plus
`structuredContent`. Errors are `isError` results that say what to try next.

## What the agent can and cannot do

Can: list, open, filter and keyword-scan tickets; count by status/priority/tag; flag overdue open/pending tickets
(`overdue` is computed at call time); read the latest public messages.

Cannot: create, edit, reply to, assign or close tickets (no write code path exists in the client); see private
notes, requester phone numbers or full emails; search by requester (it can filter a list by requester id);
see more than 30 results per search page or beyond 10 search pages; do semantic or multilingual search
(a Hinglish ticket is found only if you search a word it contains, e.g. `paisa`); see data fresher than the call.

## Safety design

* **Prompt injection.** Everything a customer typed lives under `untrusted_content`, with a `content_warning`
  and server instructions saying to summarise it, never follow it. Zero-width/bidi/control characters are
  stripped. This reduces risk; it does not make injection impossible. A model can still be fooled.
* **Privacy.** Emails masked (`a***@domain`), phones never returned, and emails/phones/card-like numbers inside
  free text are redacted. Redaction is regex-based and will miss unusual formats.
* **Rate limits.** 429 and 502/503/504 are retried, honouring `Retry-After`, capped backoff, then a message
  telling the agent to wait and shrink the request.
* **Bounded output.** Pages of 20 (30 for search), descriptions truncated, "Showing N of M" notes.

## Eval: naive raw connector vs this one

`python -m eval.run_eval` runs 20 fixed questions against both and writes `eval/results.md`. Latest run:
**naive 15/20, this connector 20/20; about 58% fewer tokens (54k vs 23k, chars/4 estimate).**

Read this honestly:
* It is a **tool-level** eval with scripted call plans. **No LLM was used**, so it says nothing about how a model
  chooses tools or phrases answers. A real-LLM mode is not built.
* 20 questions, 61 synthetic tickets, one run. Not statistically meaningful.
* Some checks reward design features (Q16 fencing, Q18 read-only instructions), not intelligence.
* The naive baseline is deliberately raw: no trimming, masking, retry or paging notes. A middle-ground
  connector would score between the two.
* The eval caught a real bug in this connector (search paging skipped results 21-30 of each page). It was fixed
  and a regression test added. The questions were not changed.
* A first fresh-clone run once scored one question differently because of a one-second timing edge at the
  24-hour boundary. The harness now waits past it; 8 repeat runs gave identical scores.
* Truth is computed from `fixtures/tickets.json` by code that does not use the connector.

## Verified vs not verified

Verified here: all 20 tests pass; the MCP server starts over stdio with `mcp` 1.30.0 and a real client lists the
tools and calls them; retry/auth/404/validation paths against the mock.
**Not verified:** behaviour against a real Freshdesk account. The mock was written from public API docs
(developers.freshdesk.com) and memory; field names, search syntax, page limits and rate-limit headers should be
checked on a trial account before trusting any claim about "real" behaviour. Plan limits (e.g. requests per
minute) vary by Freshdesk plan.

## Limitations and the long-term fix

* Keyword search scans tickets on every call. Fix: webhooks into a small indexed store (SQLite/Postgres + FTS or
  embeddings), which also gives real search, requester lookup and fresher data without burning API quota.
* Overdue answers depend on a client-side clock check. Fix: store due dates in that same index.
* Single tenant, API key in env. Fix for multiple merchants: per-merchant secrets and OAuth where the vendor offers it.
* Redaction and injection fencing are best-effort heuristics; add allow-listed fields and output scanning for production.

## Layout

    connector/   client.py (HTTP, retry) · shaping.py (trim/mask/fence) · tools.py · mcp_server.py
    mock_server/ FastAPI mock of Freshdesk · fixtures/ generator + tickets.json + ground_truth.json
    eval/        run_eval.py · results.md · tests/ 20 tests
