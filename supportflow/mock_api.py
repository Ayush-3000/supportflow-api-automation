import hmac
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="SupportFlow fictional provider APIs")
ORDERS = {
    "1042": {
        "id": "gid://shopify/Order/1042",
        "name": "#1042",
        "email": "alex@example.com",
        "displayFulfillmentStatus": "FULFILLED",
        "fulfillments": [
            {
                "trackingInfo": [
                    {
                        "company": "Demo Carrier",
                        "number": "DEMO-TRACK-1042",
                        "url": "https://example.com/tracking/1042",
                    }
                ]
            }
        ],
    },
    "1043": {
        "id": "gid://shopify/Order/1043",
        "name": "#1043",
        "email": "casey@example.com",
        "displayFulfillmentStatus": "UNFULFILLED",
        "fulfillments": [],
    },
}
REPLIES = {}


class Reply(BaseModel):
    message: str = Field(min_length=1, max_length=5000)


@app.get("/health")
def health():
    return {"status": "ok", "fictional_data": True}


@app.post("/admin/api/{version}/graphql.json")
def order_query(body: dict, x_shopify_access_token: str = Header(default="")):
    if not hmac.compare_digest(x_shopify_access_token, "demo-order-token"):
        raise HTTPException(401, "Demo provider credential required")
    if "mutation" in body.get("query", "").lower():
        raise HTTPException(403, "Demo order API is read-only")
    number = body.get("variables", {}).get("query", "").removeprefix("name:#")
    if number == "1046":
        raise HTTPException(503, "Simulated order API outage")
    return {"data": {"orders": {"nodes": [ORDERS[number]] if number in ORDERS else []}}}


@app.post("/tickets/{ticket_id}/replies")
def reply(
    ticket_id: str,
    body: Reply,
    authorization: str = Header(default=""),
    idempotency_key: str = Header(default=""),
):
    if not hmac.compare_digest(authorization, "Bearer demo-helpdesk-token"):
        raise HTTPException(401, "Demo helpdesk credential required")
    if not idempotency_key:
        raise HTTPException(400, "Idempotency-Key required")
    if idempotency_key not in REPLIES:
        REPLIES[idempotency_key] = {
            "id": f"reply-{uuid4().hex[:10]}",
            "ticket_id": ticket_id,
            "message": body.message,
            "demo_delivery": True,
        }
    return REPLIES[idempotency_key]
