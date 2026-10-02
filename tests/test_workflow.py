import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from supportflow.app import create_app, signature
from supportflow.config import Settings
from supportflow.integrations import CircuitBreaker, UpstreamError
from supportflow.mock_api import ORDERS
from supportflow.models import TicketEvent
from supportflow.store import Conflict, Store


class Provider:
    def __init__(self):
        self.orders = 0
        self.sends = []
        self.fail_order = False
        self.timeout_order = False
        self.fail_send = False
        self.throttle_once = False
        self.graphql_error = False
        self.bad_order_json = False
        self.ai_failure = False
        self.ai_calls = []

    def handle(self, request):
        data = json.loads(request.content)
        if request.url.host == "api.openai.com":
            self.ai_calls.append(data)
            if self.ai_failure:
                return httpx.Response(200, json={"status": "incomplete", "output": []})
            return httpx.Response(
                200,
                json={
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(
                                        {
                                            "reply": "Order #1042 is fulfilled. Tracking: DEMO-TRACK-1042."
                                        }
                                    ),
                                }
                            ],
                        }
                    ],
                },
            )
        if "graphql.json" in request.url.path:
            self.orders += 1
            assert request.headers["X-Shopify-Access-Token"] == "demo-order-token"
            assert request.headers["X-Correlation-ID"]
            assert "mutation" not in data["query"].lower()
            if self.timeout_order:
                raise httpx.ReadTimeout("simulated", request=request)
            if self.fail_order:
                return httpx.Response(503)
            if self.throttle_once and self.orders == 1:
                return httpx.Response(429, headers={"Retry-After": "0"})
            if self.graphql_error:
                return httpx.Response(200, json={"errors": [{"message": "access denied"}]})
            if self.bad_order_json:
                return httpx.Response(200, json={"wrong": "schema"})
            number = data["variables"]["query"].removeprefix("name:#")
            return httpx.Response(
                200,
                json={"data": {"orders": {"nodes": [ORDERS[number]] if number in ORDERS else []}}},
            )
        assert request.headers["Authorization"] == "Bearer demo-helpdesk-token"
        assert request.headers["Idempotency-Key"].startswith("supportflow-")
        self.sends.append(data)
        if self.fail_send:
            raise httpx.ReadTimeout("acknowledgement lost", request=request)
        return httpx.Response(200, json={"id": "reply-test-001"})


@pytest.fixture
def system(tmp_path):
    provider = Provider()
    settings = replace(Settings(), db_path=tmp_path / "state.sqlite", retry_base=0)
    app = create_app(settings, transport=httpx.MockTransport(provider.handle))
    with TestClient(app) as client:
        yield client, provider, app


def event(**changes):
    return {
        "schema_version": "1.0",
        "event_id": "evt-001",
        "ticket_id": "ticket-001",
        "customer_email": "alex@example.com",
        "subject": "Order status",
        "message": "Where is order #1042?",
        "order_number": "1042",
        **changes,
    }


def ingest(client, payload=None, timestamp=None, secret="demo-webhook-secret"):
    body = json.dumps(payload or event()).encode()
    stamp = str(timestamp if timestamp is not None else int(time.time()))
    return client.post(
        "/webhooks/tickets",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Timestamp": stamp,
            "X-Webhook-Signature": signature(secret, stamp, body),
        },
    )


AUTH = {"X-API-Key": "demo-local-key"}


def approve(client, row, **changes):
    return client.post(
        f"/api/tickets/{row['id']}/approve",
        headers=AUTH,
        json={
            "revision": row["revision"],
            "reviewer": "Test reviewer",
            "reply": row["draft"],
            **changes,
        },
    )


def test_order_facts_drafted_but_never_sent_automatically(system):
    client, provider, _ = system
    response = ingest(client)
    assert response.status_code == 201
    row = response.json()["ticket"]
    assert row["status"] == "pending_review"
    assert "DEMO-TRACK-1042" in row["draft"]
    assert row["facts"]["fulfillment_status"] == "FULFILLED"
    assert row["sources"][0]["id"] == "order-api"
    assert provider.orders == 1 and not provider.sends


def test_edited_reply_sent_once_with_reviewer_and_receipt(system):
    client, provider, _ = system
    row = ingest(client).json()["ticket"]
    response = approve(client, row, reply="Reviewed and edited reply.")
    sent = response.json()
    assert sent["status"] == "sent" and sent["receipt_id"] == "reply-test-001"
    assert sent["reviewer"] == "Test reviewer"
    assert provider.sends == [{"message": "Reviewed and edited reply."}]
    assert approve(client, row).status_code == 409
    assert len(provider.sends) == 1


def test_duplicate_signed_webhook_does_not_reprocess(system):
    client, provider, _ = system
    first = ingest(client).json()["ticket"]
    second = ingest(client)
    assert second.status_code == 200 and second.json()["duplicate"]
    assert second.json()["ticket"]["id"] == first["id"]
    assert provider.orders == 1


def test_same_event_changed_content_conflicts(system):
    client, provider, _ = system
    ingest(client)
    assert ingest(client, event(message="Changed request")).status_code == 409
    assert provider.orders == 1


def test_same_ticket_different_event_conflicts(system):
    client, _, _ = system
    ingest(client)
    assert ingest(client, event(event_id="evt-002")).status_code == 409


@pytest.mark.parametrize(
    "message",
    [
        "Refund my order",
        "Cancel the purchase",
        "Warranty approval",
        "Need a replacement",
        "It is overheating",
        "This is unsafe",
        "Electrical shock",
        "My order is damaged",
        "A customer was injured",
    ],
)
def test_sensitive_cases_escalate_before_api_or_ai(system, message):
    client, provider, _ = system
    row = ingest(client, event(message=message)).json()["ticket"]
    assert row["status"] == "escalated" and not row["draft"]
    assert not provider.orders and not provider.sends and not provider.ai_calls


def test_known_policy_uses_only_approved_source(system):
    client, provider, _ = system
    row = ingest(
        client, event(subject="Shipping", message="How long does shipping take?", order_number=None)
    ).json()["ticket"]
    assert row["status"] == "pending_review"
    assert row["sources"][0]["id"] == "shipping-policy"
    assert "3–5 business days" in row["draft"] and not provider.orders


def test_unknown_question_has_no_invented_answer(system):
    client, _, _ = system
    row = ingest(
        client,
        event(subject="Custom color", message="Can you make a purple edition?", order_number=None),
    ).json()["ticket"]
    assert row["status"] == "escalated" and not row["sources"] and not row["draft"]


def test_customer_mismatch_does_not_disclose_order(system):
    client, _, _ = system
    row = ingest(client, event(customer_email="another@example.com")).json()["ticket"]
    assert row["status"] == "escalated" and not row["facts"] and not row["draft"]


def test_missing_order_escalates(system):
    client, _, _ = system
    row = ingest(client, event(order_number="9999")).json()["ticket"]
    assert row["status"] == "escalated"


@pytest.mark.parametrize("flag", ["fail_order", "timeout_order"])
def test_retryable_read_failure_has_bounded_attempts_and_no_send(system, flag):
    client, provider, _ = system
    setattr(provider, flag, True)
    row = ingest(client).json()["ticket"]
    assert row["status"] == "failed" and provider.orders == 3
    assert not row["draft"] and not provider.sends


@pytest.mark.parametrize("flag", ["graphql_error", "bad_order_json"])
def test_invalid_api_results_fail_without_inventing_facts(system, flag):
    client, provider, _ = system
    setattr(provider, flag, True)
    row = ingest(client).json()["ticket"]
    assert row["status"] == "failed" and provider.orders == 1


def test_rate_limit_retried_then_drafted(system):
    client, provider, _ = system
    provider.throttle_once = True
    assert ingest(client).json()["ticket"]["status"] == "pending_review"
    assert provider.orders == 2


def test_operator_retry_recovers_failed_read(system):
    client, provider, _ = system
    provider.fail_order = True
    row = ingest(client).json()["ticket"]
    provider.fail_order = False
    retried = client.post(f"/api/tickets/{row['id']}/retry", headers=AUTH).json()
    assert retried["status"] == "pending_review" and retried["attempts"] == 2
    assert not provider.sends


def test_delivery_timeout_is_not_automatically_retried(system):
    client, provider, _ = system
    row = ingest(client).json()["ticket"]
    provider.fail_send = True
    response = approve(client, row)
    assert response.json()["status"] == "delivery_unknown"
    assert len(provider.sends) == 1
    assert approve(client, row).status_code == 409
    assert client.post(f"/api/tickets/{row['id']}/retry", headers=AUTH).status_code == 409
    assert len(provider.sends) == 1


def test_stale_revision_never_sends(system):
    client, provider, _ = system
    row = ingest(client).json()["ticket"]
    assert approve(client, row, revision=1).status_code == 409
    assert not provider.sends


@pytest.mark.parametrize("path", ["/api/tickets", "/api/demo/scenarios"])
def test_operator_reads_require_auth(system, path):
    client, _, _ = system
    assert client.get(path).status_code == 401


def test_approval_requires_auth(system):
    client, provider, _ = system
    row = ingest(client).json()["ticket"]
    result = client.post(
        f"/api/tickets/{row['id']}/approve",
        json={"revision": row["revision"], "reviewer": "Reviewer", "reply": row["draft"]},
    )
    assert result.status_code == 401 and not provider.sends


def test_signature_and_expiry_checked(system):
    client, provider, _ = system
    assert ingest(client, secret="wrong").status_code == 401
    assert ingest(client, timestamp=int(time.time()) - 301).status_code == 401
    assert not provider.orders


def test_tampering_with_signed_body_is_rejected(system):
    client, _, _ = system
    stamp = str(int(time.time()))
    original = json.dumps(event()).encode()
    body = json.dumps(event(message="tampered")).encode()
    assert (
        client.post(
            "/webhooks/tickets",
            content=body,
            headers={
                "X-Webhook-Timestamp": stamp,
                "X-Webhook-Signature": signature("demo-webhook-secret", stamp, original),
            },
        ).status_code
        == 401
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": "2.0"},
        {"customer_email": "not-an-email"},
        {"order_number": "1042 OR email:*"},
        {"ticket_id": "../../escape"},
        {"unknown_field": True},
    ],
)
def test_invalid_event_schema_rejected(system, changes):
    client, provider, _ = system
    assert ingest(client, event(**changes)).status_code == 422
    assert not provider.orders


def test_blank_reply_cannot_be_approved(system):
    client, provider, _ = system
    row = ingest(client).json()["ticket"]
    assert approve(client, row, reply="  ").status_code == 422
    assert not provider.sends


def test_persistence_and_restart_recovery(tmp_path):
    settings = replace(Settings(), db_path=tmp_path / "state.sqlite")
    store = Store(settings.db_path)
    row, _ = store.accept(TicketEvent.model_validate(event()))
    with TestClient(
        create_app(settings, transport=httpx.MockTransport(Provider().handle))
    ) as client:
        persisted = client.get(f"/api/tickets/{row['id']}", headers=AUTH).json()
        assert persisted["status"] == "failed" and "interrupted" in persisted["reason"]


def test_interrupted_delivery_recovers_to_uncertain(tmp_path):
    store = Store(tmp_path / "state.sqlite")
    row, _ = store.accept(TicketEvent.model_validate(event()))
    store.change(row["id"], {"processing"}, {"status": "sending"}, "approved", "Test interruption")
    Store(tmp_path / "state.sqlite").recover()
    assert store.get(row["id"])["status"] == "delivery_unknown"


def test_recovery_includes_tickets_older_than_dashboard_limit(tmp_path):
    store = Store(tmp_path / "state.sqlite")
    oldest, _ = store.accept(TicketEvent.model_validate(event()))
    for index in range(101):
        row, _ = store.accept(
            TicketEvent.model_validate(event(event_id=f"evt-{index + 2}", ticket_id=f"t-{index}"))
        )
        store.change(row["id"], {"processing"}, {"status": "escalated"}, "test", "Completed")
    assert oldest["id"] not in {row["id"] for row in store.list()}
    store.recover()
    assert store.get(oldest["id"])["status"] == "failed"


@pytest.mark.parametrize("reply", [None, ["unexpected"], {"reply": "nested"}])
def test_malformed_ai_reply_keeps_reference_draft(tmp_path, reply):
    provider = Provider()

    def handle(request):
        if request.url.host == "api.openai.com":
            return httpx.Response(
                200,
                json={
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {"type": "output_text", "text": json.dumps({"reply": reply})}
                            ],
                        }
                    ],
                },
            )
        return provider.handle(request)

    settings = replace(
        Settings(),
        db_path=tmp_path / "state.sqlite",
        drafter="openai",
        openai_key="fake-test-key",
        openai_model="configured-test-model",
    )
    with TestClient(create_app(settings, transport=httpx.MockTransport(handle))) as client:
        row = ingest(client).json()["ticket"]
        assert row["status"] == "pending_review" and row["provider"] == "rules"
        assert "DEMO-TRACK-1042" in row["draft"] and not provider.sends


def test_atomic_approval_claim_prevents_concurrent_double_send(tmp_path):
    store = Store(tmp_path / "state.sqlite")
    row, _ = store.accept(TicketEvent.model_validate(event()))
    store.change(row["id"], {"processing"}, {"status": "pending_review"}, "drafted", "Test")

    def claim():
        try:
            store.change(
                row["id"],
                {"pending_review"},
                {"status": "sending"},
                "approved",
                "Concurrent request",
            )
            return True
        except Conflict:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: claim(), range(2))) == [False, True]


def test_circuit_opens_and_recovers_after_cooldown():
    clock = [0.0]
    circuit = CircuitBreaker(clock=lambda: clock[0])
    for _ in range(5):
        circuit.failed()
    with pytest.raises(UpstreamError):
        circuit.check()
    clock[0] = 31
    circuit.check()
    circuit.succeeded()


@pytest.mark.parametrize("failure", [False, True])
def test_optional_ai_schema_and_safe_fallback(tmp_path, failure):
    provider = Provider()
    provider.ai_failure = failure
    settings = replace(
        Settings(),
        db_path=tmp_path / "state.sqlite",
        drafter="openai",
        openai_key="fake-test-key",
        openai_model="configured-test-model",
    )
    with TestClient(create_app(settings, transport=httpx.MockTransport(provider.handle))) as client:
        row = ingest(client).json()["ticket"]
        assert row["status"] == "pending_review" and not provider.sends
        assert row["provider"] == ("rules" if failure else "openai")
        request = provider.ai_calls[0]
        assert request["store"] is False and request["text"]["format"]["strict"] is True
        assert "customer_email" not in request["input"]


def test_live_mode_rejects_demo_defaults(monkeypatch):
    monkeypatch.setenv("SUPPORTFLOW_MODE", "live")
    monkeypatch.setenv("SHOPIFY_SHOP", "example.myshopify.com")
    with pytest.raises(ValueError, match="secrets"):
        Settings.from_env()


def test_demo_endpoint_disabled_in_live_mode(tmp_path):
    settings = replace(Settings(), mode="live", db_path=tmp_path / "state.sqlite")
    with TestClient(
        create_app(settings, transport=httpx.MockTransport(Provider().handle))
    ) as client:
        assert client.post("/api/demo/scenarios/order_status", headers=AUTH).status_code == 404


def test_dashboard_and_openapi_available(system):
    client, _, _ = system
    assert "Every reply, reviewed." in client.get("/").text
    assert client.get("/static/style.css").status_code == 200
    assert "/webhooks/tickets" in client.get("/openapi.json").json()["paths"]
