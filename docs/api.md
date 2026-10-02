# API contract

The running API exposes OpenAPI at `/openapi.json` and Swagger UI at `/docs`.

## Ticket ingestion

`POST /webhooks/tickets`

```json
{
  "schema_version": "1.0",
  "event_id": "helpdesk-event-001",
  "ticket_id": "ticket-001",
  "customer_email": "alex@example.com",
  "subject": "Order status",
  "message": "Where is order #1042?",
  "order_number": "1042"
}
```

`order_number` may be null or omitted. IDs accept letters, digits, hyphens and underscores; order numbers accept an optional `#` plus up to 25 letters, digits or hyphens. Unknown fields are rejected. The maximum message length is 5,000 characters, subject 200 characters, email 254 characters, and IDs 100 characters. The webhook body limit is 16 KiB; set a corresponding ingress limit at a reverse proxy because the app reads the request body before checking its size.

Required headers:

```text
Content-Type: application/json
X-Webhook-Timestamp: <Unix seconds as decimal text>
X-Webhook-Signature: sha256=<lowercase hex HMAC>
```

Compute the HMAC over the exact bytes `timestamp + "." + raw_request_body`, using `SUPPORTFLOW_WEBHOOK_SECRET`. Do not parse and reserialize the body between signing and sending. Timestamps must be within 300 seconds of the server clock. The event ID provides duplicate protection within the stored ticket lifecycle.

Example signing code:

```python
import hashlib
import hmac
import json
import time

body = json.dumps(event).encode("utf-8")
timestamp = str(int(time.time()))
digest = hmac.new(
    secret.encode("utf-8"), timestamp.encode() + b"." + body, hashlib.sha256
).hexdigest()
headers = {
    "Content-Type": "application/json",
    "X-Webhook-Timestamp": timestamp,
    "X-Webhook-Signature": "sha256=" + digest,
}
```

Returns `{ "ticket": <record>, "duplicate": false }` with 201 for a new ticket, or the existing record with 200 and `duplicate: true`. The ticket may be pending review, escalated or failed; these are workflow outcomes, not ingestion HTTP errors. If a helpdesk or n8n workflow uses another native signature format, add a trusted gateway that validates its signature and maps to this schema.

## Operator endpoints

All `/api/` routes require `X-API-Key: <SUPPORTFLOW_API_KEY>`.

| Method / route | Description |
| --- | --- |
| `GET /api/tickets` | Most recent 100 records, mode and drafting provider |
| `GET /api/tickets/{id}` | Full record, selected evidence and audit history |
| `POST /api/tickets/{id}/approve` | Claim a current pending draft and send the edited reply once |
| `POST /api/tickets/{id}/retry` | Replay a failed read workflow; maximum five workflow attempts |
| `GET /api/demo/scenarios` | Fictional scenario definitions; demo mode only |
| `POST /api/demo/scenarios/{scenario}` | Authenticated demo injection; demo mode only |
| `GET /health` | Public health, mode and provider; no ticket data |

Approval body:

```json
{
  "revision": 2,
  "reviewer": "Demo reviewer",
  "reply": "Order #1042 is fulfilled. Tracking number: DEMO-TRACK-1042."
}
```

The `id` in the operator URL is the internal UUID returned in the record, not the external `ticket_id`. Retrieve the current revision immediately before approval. Replies are limited to 5,000 characters and reviewer labels to 100; neither can be blank. The reviewer label is not an authenticated identity. A successful approval request may return `delivery_unknown`; inspect the status and receipt rather than treating any HTTP 200 as proof of delivery.

Common errors: 401 for invalid authentication/signature, 404 for missing records or unavailable demo routes, 409 for conflicting event/state/revision or retry exhaustion, 413 for oversized webhook bodies, and 422 for invalid schemas.

## Order API adapter

Live endpoint: `https://<canonical-shop>.myshopify.com/admin/api/<version>/graphql.json`.

Authentication: `X-Shopify-Access-Token`. Request correlation: `X-Correlation-ID`.

The adapter uses a GraphQL **query**, with a search variable `name:#<number>`, requesting order name, email, fulfillment status and tracking info. Results must contain exactly one order matching both name and email. No matching facts are persisted when that check fails. A trusted upstream must supply the customer's email; equality of two email fields does not authenticate a customer.

Shopify scopes and protected customer data access are configured outside this project. The included adapter is contract-tested against a Shopify-shaped mock, not a real store. Test the selected API version, permissions, identity handling and response shape against a development store before live use.

## Reference helpdesk gateway

`POST <HELPDESK_URL>/tickets/<external-ticket-id>/replies`

```text
Authorization: Bearer <HELPDESK_API_KEY>
Idempotency-Key: supportflow-<internal-ticket-uuid>
X-Correlation-ID: <internal-ticket-uuid>
Content-Type: application/json
```

```json
{ "message": "The human-reviewed reply text" }
```

Expected success: a 2xx response containing a non-empty string receipt:

```json
{ "id": "reply-provider-001" }
```

A gateway should map ticket IDs safely, enforce the provider's permissions and preserve idempotency durably. It should return the same receipt for the same idempotency key and reject reuse with a different payload. SupportFlow does not automatically retry this write. A malformed receipt, non-2xx response or network error becomes `delivery_unknown` and requires operator reconciliation.

This contract is a reference adapter, not LiveAgent's native API. To use LiveAgent, Zendesk or another provider, implement this gateway or replace `Integrations.send` and add real-provider tests. The local mock keeps receipts in memory and cannot prove idempotency across mock process restarts.
