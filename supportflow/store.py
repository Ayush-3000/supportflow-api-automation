import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .models import TicketEvent


class Conflict(Exception):
    pass


class Missing(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def audit(row, action, detail):
    row["audit"].append({"at": now(), "action": action, "detail": detail})
    row["updated_at"] = now()


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS tickets (id TEXT PRIMARY KEY, event_id TEXT UNIQUE, ticket_id TEXT UNIQUE, payload_hash TEXT NOT NULL, record TEXT NOT NULL)"
            )

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def accept(self, event: TicketEvent):
        payload = event.model_dump(mode="json")
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT payload_hash, record FROM tickets WHERE event_id=? OR ticket_id=?",
                (event.event_id, event.ticket_id),
            ).fetchone()
            if existing:
                row = json.loads(existing[1])
                if existing[0] != digest:
                    raise Conflict("Event or ticket ID already exists with different content")
                return row, False
            row = {
                "id": str(uuid4()),
                "event": payload,
                "status": "processing",
                "category": "pending",
                "reason": "",
                "draft": "",
                "sources": [],
                "facts": {},
                "audit": [],
                "revision": 1,
                "attempts": 1,
                "created_at": now(),
                "updated_at": now(),
                "provider": "rules",
            }
            audit(row, "received", "Ticket accepted; duplicate protection enabled")
            db.execute(
                "INSERT INTO tickets VALUES (?, ?, ?, ?, ?)",
                (row["id"], event.event_id, event.ticket_id, digest, json.dumps(row)),
            )
            return row, True

    def get(self, ticket_id):
        with self.connection() as db:
            result = db.execute("SELECT record FROM tickets WHERE id=?", (ticket_id,)).fetchone()
        if not result:
            raise Missing("Ticket not found")
        return json.loads(result[0])

    def list(self):
        with self.connection() as db:
            rows = db.execute("SELECT record FROM tickets ORDER BY rowid DESC LIMIT 100").fetchall()
        return [json.loads(row[0]) for row in rows]

    def change(self, ticket_id, allowed, changes, action, detail, revision=None):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            result = db.execute("SELECT record FROM tickets WHERE id=?", (ticket_id,)).fetchone()
            if not result:
                raise Missing("Ticket not found")
            row = json.loads(result[0])
            if row["status"] not in allowed or (
                revision is not None and revision != row["revision"]
            ):
                raise Conflict("Ticket state or revision changed; refresh before taking action")
            row.update(changes)
            row["revision"] += 1
            audit(row, action, detail)
            db.execute("UPDATE tickets SET record=? WHERE id=?", (json.dumps(row), ticket_id))
        return row

    def recover(self):
        with self.connection() as db:
            records = db.execute("SELECT record FROM tickets").fetchall()
        for record in records:
            row = json.loads(record[0])
            if row["status"] == "processing":
                self.change(
                    row["id"],
                    {"processing"},
                    {"status": "failed", "reason": "Processing interrupted; safe to retry"},
                    "recovered",
                    "Interrupted read workflow moved to retry queue",
                )
            elif row["status"] == "sending":
                self.change(
                    row["id"],
                    {"sending"},
                    {
                        "status": "delivery_unknown",
                        "reason": "Delivery interrupted; check the helpdesk before another send",
                    },
                    "recovered",
                    "Ambiguous delivery requires reconciliation",
                )
