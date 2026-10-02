"""Sign and submit a fictional ticket using only the Python standard library."""

import argparse
import hashlib
import hmac
import json
import os
import time
from urllib.request import Request, urlopen
from uuid import uuid4

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8000/webhooks/tickets")
parser.add_argument(
    "--event-id",
    default=None,
    help="Reuse an ID with the same ticket content to demonstrate deduplication",
)
args = parser.parse_args()
event_id = args.event_id or f"evt-{uuid4().hex[:10]}"
payload = {
    "schema_version": "1.0",
    "event_id": event_id,
    "ticket_id": f"ticket-{event_id}",
    "customer_email": "alex@example.com",
    "subject": "Order status",
    "message": "Could you check the status of order #1042?",
    "order_number": "1042",
}
body = json.dumps(payload).encode()
timestamp = str(int(time.time()))
secret = os.getenv("SUPPORTFLOW_WEBHOOK_SECRET", "demo-webhook-secret")
digest = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
request = Request(
    args.url,
    data=body,
    headers={
        "Content-Type": "application/json",
        "X-Webhook-Timestamp": timestamp,
        "X-Webhook-Signature": f"sha256={digest}",
    },
    method="POST",
)
with urlopen(request, timeout=20) as response:
    print(json.dumps(json.load(response), indent=2))
