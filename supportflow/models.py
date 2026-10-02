import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TicketEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    event_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    ticket_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    customer_email: str = Field(max_length=254)
    subject: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=5000)
    order_number: str | None = Field(default=None, max_length=30)

    @field_validator("customer_email")
    @classmethod
    def validate_email(cls, value):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("A valid customer email is required")
        return value.strip().lower()

    @field_validator("order_number")
    @classmethod
    def validate_order(cls, value):
        if value is not None and not re.fullmatch(r"#?[A-Za-z0-9-]{1,25}", value):
            raise ValueError("Invalid order number")
        return value.lstrip("#") if value else None


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    reviewer: str = Field(min_length=1, max_length=100)
    reply: str = Field(min_length=1, max_length=5000)

    @field_validator("reply", "reviewer")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Cannot be blank")
        return value.strip()
