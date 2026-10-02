import json
import re
from pathlib import Path

from .integrations import UpstreamError
from .models import Approval, TicketEvent
from .store import Conflict

RISK_WORDS = re.compile(
    r"\b(refund\w*|cancel\w*|warrant\w*|replacement\w*|unsafe|safety|fire|shock|overheat\w*|smoke|damag\w*|broken|electrical|chargeback\w*|lawyer|injur\w*)\b",
    re.I,
)


class Service:
    def __init__(self, store, integrations, settings):
        self.store, self.api, self.settings = store, integrations, settings
        self.knowledge = json.loads(
            (Path(__file__).parent / "data" / "knowledge.json").read_text(encoding="utf-8")
        )

    def ingest(self, event):
        row, created = self.store.accept(event)
        return (self.process(row) if created else row), not created

    def process(self, row):
        event = TicketEvent.model_validate(row["event"])
        text = f"{event.subject} {event.message}".lower()
        risk = RISK_WORDS.search(text)
        if risk:
            return self.store.change(
                row["id"],
                {"processing"},
                {
                    "status": "escalated",
                    "category": "sensitive",
                    "reason": f"Human handling required: {risk.group(0)}",
                },
                "escalated",
                "Sensitive request; no model call, order disclosure, or automated delivery",
            )
        facts, sources, category = {}, [], "general"
        try:
            if event.order_number and re.search(
                r"\b(order|track\w*|status|package|parcel|shipment)\b", text
            ):
                category = "order_status"
                facts = self.api.order(event.order_number, event.customer_email, row["id"])
                if facts is None:
                    return self.store.change(
                        row["id"],
                        {"processing"},
                        {
                            "status": "escalated",
                            "category": category,
                            "reason": "Order and customer email could not be uniquely matched",
                        },
                        "escalated",
                        "Customer/order match required before sharing order data",
                    )
                sources = [
                    {
                        "id": "order-api",
                        "title": "Verified order API response",
                        "text": json.dumps(facts),
                    }
                ]
                status = facts["fulfillment_status"].replace("_", " ").lower()
                tracking = facts["tracking"]
                detail = (
                    f" Tracking number: {tracking[0]['number']}."
                    if tracking and tracking[0].get("number")
                    else " No tracking number is available yet."
                )
                draft = f"Thanks for reaching out. Order {facts['order_number']} currently has fulfillment status: {status}.{detail} Please let us know if you need further help."
            else:
                tokens = set(re.findall(r"[a-z]+", text))
                scores = [
                    (len(tokens.intersection(doc["keywords"])), doc) for doc in self.knowledge
                ]
                score, source = max(scores, key=lambda item: item[0])
                if score == 0:
                    return self.store.change(
                        row["id"],
                        {"processing"},
                        {
                            "status": "escalated",
                            "category": "unknown",
                            "reason": "No approved knowledge source matches this request",
                        },
                        "escalated",
                        "Unsupported question routed to human; no invented answer",
                    )
                category = "knowledge_question"
                sources = [source]
                draft = f"Thanks for your question. {source['text']} Please let us know if you need further assistance."
        except UpstreamError as error:
            return self.store.change(
                row["id"],
                {"processing"},
                {"status": "failed", "category": category, "reason": str(error)},
                "integration_failed",
                "Read workflow added to retry queue; no response sent",
            )
        provider, note = "rules", "Draft generated from verified API facts or approved knowledge"
        if self.settings.drafter == "openai":
            try:
                draft = self.api.ai_draft(event.message, facts, sources, draft)
                provider = "openai"
                note = "AI draft generated; factual review required before approval"
            except UpstreamError as error:
                note = str(error)
        return self.store.change(
            row["id"],
            {"processing"},
            {
                "status": "pending_review",
                "category": category,
                "facts": facts,
                "sources": sources,
                "draft": draft,
                "provider": provider,
                "reason": "Human approval required before delivery",
            },
            "drafted",
            note,
        )

    def approve(self, ticket_id, approval: Approval):
        row = self.store.change(
            ticket_id,
            {"pending_review"},
            {"status": "sending", "approved_reply": approval.reply, "reviewer": approval.reviewer},
            "approved",
            f"Reply approved by {approval.reviewer}",
            revision=approval.revision,
        )
        try:
            receipt = self.api.send(
                row["event"]["ticket_id"], approval.reply, f"supportflow-{row['id']}", row["id"]
            )
        except UpstreamError as error:
            return self.store.change(
                ticket_id,
                {"sending"},
                {"status": "delivery_unknown", "reason": str(error)},
                "delivery_unknown",
                "No automatic resend; reconcile with provider first",
            )
        return self.store.change(
            ticket_id,
            {"sending"},
            {
                "status": "sent",
                "receipt_id": receipt,
                "reason": "Approved reply delivered to helpdesk",
            },
            "delivered",
            "Helpdesk acknowledged delivery",
        )

    def retry(self, ticket_id):
        row = self.store.get(ticket_id)
        if row["attempts"] >= 5:
            raise Conflict("Retry limit reached; investigate the upstream API")
        row = self.store.change(
            ticket_id,
            {"failed"},
            {"status": "processing", "attempts": row["attempts"] + 1},
            "retry_started",
            "Operator requested another read attempt",
            revision=row["revision"],
        )
        return self.process(row)
