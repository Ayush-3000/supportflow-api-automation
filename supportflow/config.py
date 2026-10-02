import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    mode: str = "demo"
    api_key: str = "demo-local-key"
    webhook_secret: str = "demo-webhook-secret"
    db_path: Path = Path("runtime/supportflow.sqlite")
    shopify_url: str = "http://127.0.0.1:8001/admin/api/2026-07/graphql.json"
    shopify_token: str = "demo-order-token"
    helpdesk_url: str = "http://127.0.0.1:8001"
    helpdesk_key: str = "demo-helpdesk-token"
    drafter: str = "rules"
    openai_key: str = ""
    openai_model: str = ""
    retry_base: float = 0.15
    request_timeout: float = 4.0

    @classmethod
    def from_env(cls):
        mode = os.getenv("SUPPORTFLOW_MODE", "demo")
        if mode not in {"demo", "live"}:
            raise ValueError("SUPPORTFLOW_MODE must be demo or live")
        shopify_url = cls.shopify_url
        if mode == "live":
            shop = os.getenv("SHOPIFY_SHOP", "")
            version = os.getenv("SHOPIFY_API_VERSION", "2026-07")
            if not re.fullmatch(r"[a-z0-9-]+\.myshopify\.com", shop):
                raise ValueError("SHOPIFY_SHOP must be your canonical myshopify.com domain")
            if not re.fullmatch(r"20\d{2}-(01|04|07|10)", version):
                raise ValueError("Set a stable Shopify API version")
            shopify_url = f"https://{shop}/admin/api/{version}/graphql.json"
        settings = cls(
            mode=mode,
            api_key=os.getenv("SUPPORTFLOW_API_KEY", "demo-local-key" if mode == "demo" else ""),
            webhook_secret=os.getenv(
                "SUPPORTFLOW_WEBHOOK_SECRET", "demo-webhook-secret" if mode == "demo" else ""
            ),
            db_path=Path(os.getenv("SUPPORTFLOW_DB", "runtime/supportflow.sqlite")),
            shopify_url=shopify_url,
            shopify_token=os.getenv(
                "SHOPIFY_ACCESS_TOKEN", "demo-order-token" if mode == "demo" else ""
            ),
            helpdesk_url=os.getenv("HELPDESK_URL", cls.helpdesk_url if mode == "demo" else ""),
            helpdesk_key=os.getenv(
                "HELPDESK_API_KEY", "demo-helpdesk-token" if mode == "demo" else ""
            ),
            drafter=os.getenv("SUPPORTFLOW_DRAFTER", "rules"),
            openai_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", ""),
        )
        if settings.drafter not in {"rules", "openai"}:
            raise ValueError("SUPPORTFLOW_DRAFTER must be rules or openai")
        if settings.drafter == "openai" and not (settings.openai_key and settings.openai_model):
            raise ValueError("AI drafting needs OPENAI_API_KEY and OPENAI_MODEL")
        if mode == "live":
            if len(settings.api_key) < 32 or len(settings.webhook_secret) < 32:
                raise ValueError(
                    "Live mode requires unique SupportFlow secrets of at least 32 characters"
                )
            if not settings.shopify_token or not settings.helpdesk_key:
                raise ValueError("Live mode requires Shopify and helpdesk credentials")
            url = urlsplit(settings.helpdesk_url)
            if url.scheme != "https" or not url.netloc or url.username or url.password:
                raise ValueError(
                    "Live helpdesk gateway must use HTTPS without credentials in its URL"
                )
        return settings
