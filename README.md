# StitchNest Helpdesk Connector
### Read-Only Freshdesk MCP Server for Agent Studio-Style Support Agents

## Razorpay Assignment 3

This repository implements **Assignment 3: Build a private connector for a merchant tool**.

**Merchant tool:** Freshdesk  
**Connector:** Read-only Freshdesk MCP connector  
**Authentication:** Freshdesk API key  
**Transport:** MCP over stdio  
**Data:** Synthetic/mock Freshdesk tickets for evaluation

---

## The Story

StitchNest is a fictional Indian D2C apparel brand that takes payments through Razorpay.

Its support lead can't easily tell:

- Which tickets are urgent
- Which tickets are related to payments
- Which customers report "money debited, order not confirmed"
- Which tickets are about refunds or failed UPI payments
- Which tickets are approaching or have breached SLA

This connector lets an AI agent answer those questions from Freshdesk ticket data while keeping access deliberately bounded.

The connector is designed around four principles:

- **Read-only access**
- **Bounded output**
- **Customer PII masking**
- **Customer-written content treated as untrusted data**

Everything can be run locally with **synthetic data and no credentials**.

---

## Assignment 3 Requirement Checklist

| Assignment requirement | Implementation |
|---|---|
| Merchant tool | Freshdesk |
| Private connector | Python Freshdesk connector |
| Agent access | MCP server |
| Authentication | Freshdesk API key |
| List primitive | `list_tickets` |
| Get primitive | `get_ticket` |
| Search primitives | `search_tickets`, `find_by_keyword` |
| Rate-limit handling | 429 + 502/503/504 retry handling |
| MCP specification/equivalent | MCP tools using the official MCP SDK |
| Read-only boundaries | All tools are read-only; no write code path |
| Can/cannot documentation | Documented below |
| Setup instructions | Included below |
| Run instructions | Included below |
| Assumptions | Included below |
| Limitations | Included below |
| Test data | 61 synthetic Freshdesk tickets |
| Automated tests | 20 tests |
| Evaluation | Deterministic 20-question tool-level evaluation |
| Credentials in repository | None |

---

## Intended Agent Workflow

```text
Support lead question
        |
        v
Agent selects an appropriate read-only tool
        |
        v
MCP connector retrieves bounded Freshdesk data
        |
        v
PII is masked and customer content is fenced as untrusted
        |
        v
Agent summarizes the retrieved information
