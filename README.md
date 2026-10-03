## Limitations

The connector is intentionally scoped as a take-home assignment and has several limitations.

### 1. Keyword search is bounded

Freshdesk does not provide unrestricted free-text search through this connector.

`find_by_keyword` scans a bounded number of recent ticket pages and performs an exact substring match.

Therefore:

- It may not find older tickets outside the configured search window.
- It does not understand synonyms.
- It does not perform semantic search.
- It does not translate between languages.
- For example, a Hinglish ticket containing `paisa` will be found when searching for `paisa`, but not necessarily when searching for `payment`.

For production use, an indexed search layer such as PostgreSQL full-text search, Elasticsearch/OpenSearch, or embeddings could provide broader and semantic search.

---

### 2. Search results are intentionally bounded

The connector limits the amount of data returned to the agent.

Current limits include:

- Maximum tickets per list page
- Maximum tickets per search page
- Maximum number of pages scanned during keyword search
- Maximum description length returned
- Maximum number of public messages returned for a ticket

This prevents unnecessarily large responses and reduces token usage.

The trade-off is that the agent cannot retrieve an unlimited number of tickets in a single operation.

---

### 3. No write operations

This connector is strictly read-only.

The agent cannot:

- Create tickets
- Edit tickets
- Reply to customers
- Assign tickets
- Change ticket status
- Close tickets
- Delete tickets
- Add internal notes
- Modify Freshdesk data

There is deliberately no write code path in the connector.

---

### 4. API-key authentication is single-tenant

The current implementation uses a Freshdesk API key supplied through an environment variable.

This is suitable for a single-merchant evaluation environment but is not a complete multi-tenant credential-management system.

A production implementation would require:

- Per-merchant credential isolation
- Secure secret storage
- Credential rotation
- OAuth where supported
- Access-control policies
- Audit logging

---

### 5. PII masking is best-effort

The connector masks customer email addresses and removes phone numbers and card-like numbers from returned content.

However, the redaction is regex-based.

Therefore, unusual or previously unseen formats may not be detected.

For production use, sensitive-field allow-listing and additional output scanning would provide stronger protection.

---

### 6. Prompt-injection protection is not absolute

Customer-written ticket content is treated as **untrusted content**.

The connector:

- Places customer text under `untrusted_content`
- Adds content warnings
- Removes zero-width, bidi, and control characters
- Instructs the agent not to follow instructions contained inside ticket text

These measures reduce the risk of prompt injection, but they cannot guarantee that a future model will never be influenced by malicious customer content.

Production deployments should combine this approach with stronger model-level and application-level security controls.

---

### 7. Rate limits depend on Freshdesk

The connector retries transient failures such as:

- `429 Too Many Requests`
- `502 Bad Gateway`
- `503 Service Unavailable`
- `504 Gateway Timeout`

It respects `Retry-After` when available and uses bounded backoff.

However, actual Freshdesk rate limits depend on the merchant's Freshdesk plan and account configuration.

The connector therefore does not assume a universal requests-per-minute limit.

---

### 8. Mock data does not represent real customer data

The repository uses **61 synthetic Freshdesk tickets**.

The tickets include intentionally difficult cases such as:

- Payment failures
- Refund requests
- UPI failures
- Overdue tickets
- Empty descriptions
- Long descriptions
- Near-duplicate tickets
- Hinglish text
- Prompt-injection-style content
- Rate-limit scenarios

No real customer data is required to run the evaluation.

---

### 9. Evaluation is not an LLM benchmark

The repository includes a deterministic 20-question evaluation comparing:

- A naive/raw connector interface
- The agent-friendly connector

The latest evaluation produced:

- Naive interface: **15/20**
- Agent-friendly connector: **20/20**
- Approximately **58% lower estimated token usage**

However, this evaluation uses **scripted tool-call plans and synthetic data**.

It does **not** measure:

- LLM reasoning accuracy
- LLM tool-selection accuracy
- Natural-language answer quality
- Hallucination rate
- Production agent performance

Therefore, the evaluation should be interpreted as a **tool/interface evaluation**, not as proof of LLM performance.

---

### 10. Freshness depends on the Freshdesk API

The connector retrieves information when the agent makes a request.

It does not maintain a continuously synchronized local database.

Therefore:

- There is no guaranteed real-time event stream.
- There is no historical local index.
- Repeated keyword searches may make repeated API calls.

A production architecture could use Freshdesk webhooks/events to populate an indexed store such as PostgreSQL or another search system.

---

### 11. Overdue status is calculated at request time

Whether a ticket is overdue is determined using the current time when the connector processes the request.

This means the overdue state is not permanently stored by the connector.

A production system could maintain SLA state in an indexed datastore and optionally process SLA events continuously.

---

### 12. Single-merchant scope

The current implementation is designed around one merchant environment.

It does not provide a complete multi-merchant control plane for:

- Merchant onboarding
- Tenant isolation
- Per-tenant credentials
- Per-tenant rate limits
- Per-tenant configuration
- Centralized audit logs

These would be required for a production SaaS deployment.

---

### 13. API compatibility should be validated before production use

The local mock server is used for deterministic testing and evaluation.

Before production deployment, the connector should be validated against the target Freshdesk account and plan for:

- API response fields
- Pagination behavior
- Search behavior
- Authentication behavior
- Rate-limit headers
- Error responses
- Plan-specific restrictions

The mock should therefore be considered a testing substitute, not a complete replica of every Freshdesk behavior.

---

## Assumptions

The implementation makes the following assumptions:

1. The merchant has a Freshdesk account and an API key with permission to read the required ticket data.
2. The connector is used by a trusted Agent Studio-style agent.
3. Ticket content must be treated as untrusted customer data.
4. Read-only access is sufficient for the assignment.
5. API credentials are supplied through environment variables rather than committed to source control.
6. Synthetic ticket data is sufficient for deterministic testing.
7. The agent can make multiple tool calls when a question requires additional ticket information.
8. The connector's bounded search and output limits are acceptable trade-offs for predictable token usage and safety.
9. Production deployments would require stronger secret management, monitoring, tenant isolation, and persistent indexing.
