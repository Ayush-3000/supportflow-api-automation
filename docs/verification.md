# Verification record

Recorded on 2026-10-03 using the local Python environment on Windows.

## Automated checks

- `python -m pytest -q`: **50 passed**.
- `python -m ruff check .`: passed.
- `python -m ruff format --check .`: passed.
- Frontend JavaScript, CSS and HTML formatted with Prettier; JavaScript syntax checked with Node.

The HTTP contract tests replace external providers with an HTTPX mock transport. They verify the read-only Shopify query, OpenAI request/response contract, helpdesk message payloads, signatures, retry behavior, persistence and approval state. They do not establish live-provider compatibility.

The installed Starlette test client emits a deprecation warning about its HTTPX integration. It does not fail the tests; the application still uses HTTPX for outbound provider requests.

## Local two-service demonstration

The workflow API and fictional provider API ran as separate processes on ports 8000 and 8001. The browser dashboard was checked with actual HTTP requests between those processes.

| Check | Observed result |
| --- | --- |
| Order lookup | Verified fulfillment and tracking evidence; draft waits for review |
| Shipping policy | Approved source and policy draft displayed |
| Edited reply approval | Local mock helpdesk acknowledged delivery; reviewer label and receipt recorded |
| Refund request | Escalated with no draft |
| Customer mismatch | Order facts withheld; human escalation |
| Unknown question | Escalated without an invented answer |
| API outage | Failed read workflow; bounded retries; operator replay remains failed while outage persists |
| Repeated outage calls | Circuit blocks new order lookups during its cooldown |
| Signed webhook replay | New ingestion returns 201; identical replay returns 200 with the same stored ticket |

Screenshots were captured from the working review and delivery screens using fictional data. A mobile-width layout check confirmed that the review tools remain usable in a single-column view.

## Verification limits

- No live Shopify store, native LiveAgent service or paid OpenAI model call was used.
- Docker and Compose were supplied but were not executed in this environment.
- No real customer message or Upwork application was submitted.
- No load test, penetration test, multi-worker deployment or verified reviewer identity system is included.
- This reference is a portfolio demonstration; live deployment requires provider validation and the operational controls described in the README.
