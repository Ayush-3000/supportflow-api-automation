import hashlib
import hmac
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from .config import Settings
from .integrations import Integrations
from .models import Approval, TicketEvent
from .scenarios import SCENARIOS
from .service import Service
from .store import Conflict, Missing, Store


def signature(secret, timestamp, body):
    return (
        "sha256="
        + hmac.new(
            secret.encode(), str(timestamp).encode() + b"." + body, hashlib.sha256
        ).hexdigest()
    )


def create_app(settings=None, transport=None):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        store = Store(settings.db_path)
        store.recover()
        integrations = Integrations(settings, transport=transport)
        app.state.service = Service(store, integrations, settings)
        yield
        integrations.close()

    app = FastAPI(title="SupportFlow API", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings
    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    def authenticated(x_api_key: str = Header(default="")):
        if not hmac.compare_digest(x_api_key, settings.api_key):
            raise HTTPException(401, "Valid X-API-Key required")

    @app.exception_handler(Conflict)
    async def conflict_handler(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(Missing)
    async def missing_handler(request, exc):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(static / "index.html")

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": settings.mode, "drafter": settings.drafter}

    @app.get("/api/tickets", dependencies=[Depends(authenticated)])
    def tickets():
        return {
            "tickets": app.state.service.store.list(),
            "mode": settings.mode,
            "drafter": settings.drafter,
        }

    @app.get("/api/tickets/{ticket_id}", dependencies=[Depends(authenticated)])
    def ticket(ticket_id: str):
        return app.state.service.store.get(ticket_id)

    @app.post("/api/tickets/{ticket_id}/approve", dependencies=[Depends(authenticated)])
    def approve(ticket_id: str, approval: Approval):
        return app.state.service.approve(ticket_id, approval)

    @app.post("/api/tickets/{ticket_id}/retry", dependencies=[Depends(authenticated)])
    def retry(ticket_id: str):
        return app.state.service.retry(ticket_id)

    @app.post("/webhooks/tickets")
    async def webhook(
        request: Request,
        x_webhook_timestamp: str = Header(default=""),
        x_webhook_signature: str = Header(default=""),
    ):
        if not x_webhook_timestamp.isdigit() or abs(time.time() - int(x_webhook_timestamp)) > 300:
            raise HTTPException(401, "Webhook timestamp invalid or expired")
        body = await request.body()
        if len(body) > 16384:
            raise HTTPException(413, "Webhook payload too large")
        expected = signature(settings.webhook_secret, x_webhook_timestamp, body)
        if not hmac.compare_digest(expected, x_webhook_signature):
            raise HTTPException(401, "Webhook signature invalid")
        try:
            event = TicketEvent.model_validate_json(body)
        except ValidationError:
            raise HTTPException(422, "Ticket does not match the versioned event schema") from None
        row, duplicate = await run_in_threadpool(app.state.service.ingest, event)
        return JSONResponse(
            status_code=200 if duplicate else 201, content={"ticket": row, "duplicate": duplicate}
        )

    @app.get("/api/demo/scenarios", dependencies=[Depends(authenticated)])
    def scenarios():
        if settings.mode != "demo":
            raise HTTPException(404, "Demo scenarios unavailable in live mode")
        return [
            {"id": key, "label": value["label"], "description": value["description"]}
            for key, value in SCENARIOS.items()
        ]

    @app.post("/api/demo/scenarios/{scenario}", dependencies=[Depends(authenticated)])
    def run_scenario(scenario: str):
        if settings.mode != "demo" or scenario not in SCENARIOS:
            raise HTTPException(404, "Demo scenario not available")
        sample = {
            key: value
            for key, value in SCENARIOS[scenario].items()
            if key not in {"label", "description"}
        }
        event = TicketEvent(
            event_id=f"demo-{uuid4().hex}", ticket_id=f"SF-{uuid4().hex[:8]}", **sample
        )
        row, _ = app.state.service.ingest(event)
        return row

    return app
