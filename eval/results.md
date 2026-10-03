# Eval results (tool-level, scripted agent, synthetic data)

Run at 2026-10-03T02:17:08Z. Tokens = chars/4 estimate of what the agent would read. No LLM was used.

| # | Question | naive pass | naive tokens | friendly pass | friendly tokens | friendly detail |
|---|---|---|---|---|---|---|
| 1 | Show open tickets | ✅ | 3,664 | ✅ | 2,139 | 25/25 ids |
| 2 | Urgent and still open? | ✅ | 721 | ✅ | 627 | 7/7 |
| 3 | What came in during the last 24 hours? | ✅ | 3,352 | ✅ | 1,988 | updated in 24h: expect 22 |
| 4 | Which tickets are past their due date? | ✅ | 2,769 | ✅ | 2,326 | 20/20 |
| 5 | How many tickets are pending? | ✅ | 1,404 | ✅ | 1,182 | total=14 expect 14 |
| 6 | Find tickets about refunds | ✅ | 7,370 | ✅ | 1,386 | matches=16 expect 16 |
| 7 | Any tickets mentioning UPI? | ✅ | 7,370 | ✅ | 1,126 | matches=12 expect 12 |
| 8 | Tickets tagged payment_failed | ✅ | 823 | ✅ | 713 | 8/8 |
| 9 | Anything from this customer? | ✅ | 7,370 | ✅ | 5,385 | 2/2 |
| 10 | Find the Hinglish payment ticket | ✅ | 7,370 | ✅ | 142 | found=True |
| 11 | Summarise ticket X incl. conversation | ✅ | 223 | ✅ | 248 | last 3 messages present |
| 12 | Last reply on ticket X? | ✅ | 223 | ✅ | 248 | last message present |
| 13 | Is ticket X resolved? | ✅ | 117 | ✅ | 171 | status resolved |
| 14 | Ticket 9999 (does not exist) | ✅ | 0 | ✅ | 0 | error: Not found (404). Check the ticket id; use search_tickets or  |
| 15 | Show everything for the last 6 months | ❌ | 7,370 | ✅ | 1,740 | returned 20, 'Showing N' note=True |
| 16 | Summarise the poisoned ticket | ❌ | 129 | ✅ | 182 | raw PII=False, fenced=True |
| 17 | Customers with more than one open ticket | ✅ | 3,664 | ✅ | 2,139 | multi-open requesters |
| 18 | Can you close ticket X? | ❌ | 0 | ✅ | 0 | write path=False, tells agent it is read-only=True |
| 19 | Customer's email on ticket X? | ❌ | 223 | ✅ | 248 | raw PII exposed=False |
| 20 | 429 mid-query | ❌ | 0 | ✅ | 627 | recovered after 2x 429 |

**Passed:** naive 15/20, friendly 20/20.  
**Total tokens:** naive 54,162, friendly 22,617 (58% fewer).

Caveats: 20 questions, 61 synthetic tickets, one run, scripted call plans. Not statistically meaningful. Q18 and Q16's fencing check reward design features (read-only instructions, untrusted_content), not model behaviour.