"""Settings, read once from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./nodewright.db"
    public_url: str = "http://localhost:8080"
    """Where the app is reached. The OIDC redirect URI derives from it, and an
    https URL turns on Secure / __Host- cookies."""
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    session_ttl_days: int = 30
    max_canvas_bytes: int = 5 * 1024 * 1024
    static_dir: str | None = None
    s3_endpoint: str | None = None
    """AIStor/S3 API for attachments, e.g. http://192.168.0.10:30320."""
    s3_bucket: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_region: str = "us-east-1"
    attachments_dir: str | None = None
    """Local alternative to S3 (development); attachments are off with neither."""
    max_attachment_bytes: int = 20 * 1024 * 1024
    browserless_url: str | None = None
    """browserless (headless Chromium) for render_canvas, e.g.
    http://browserless.scrape-stack.svc:3000; render_canvas is off without it."""
    render_base_url: str | None = None
    """Where that browser reaches this app (in-cluster service URL); defaults to public_url."""
    dev_login: bool = False
    """Local-only sign-in without authentik, for development and UI tests.
    Refused when public_url is https, so it can't be switched on in prod."""

    @property
    def secure(self) -> bool:
        return self.public_url.startswith("https://")

    @property
    def oidc_enabled(self) -> bool:
        return bool(self.oidc_issuer and self.oidc_client_id and self.oidc_client_secret)

    @property
    def dev_login_enabled(self) -> bool:
        return self.dev_login and not self.secure

    @classmethod
    def from_env(cls, env=os.environ) -> "Settings":
        return cls(
            database_url=env.get("DATABASE_URL") or cls.database_url,
            public_url=(env.get("PUBLIC_URL") or cls.public_url).rstrip("/"),
            # authentik's issuer ends in "/" and the ID token's iss must match it
            # exactly, so it is kept as configured.
            oidc_issuer=(env.get("OIDC_ISSUER") or "").strip() or None,
            oidc_client_id=env.get("OIDC_CLIENT_ID") or None,
            oidc_client_secret=env.get("OIDC_CLIENT_SECRET") or None,
            session_ttl_days=int(env.get("SESSION_TTL_DAYS") or cls.session_ttl_days),
            max_canvas_bytes=int(env.get("MAX_CANVAS_BYTES") or cls.max_canvas_bytes),
            static_dir=env.get("STATIC_DIR") or None,
            s3_endpoint=env.get("S3_ENDPOINT") or None,
            s3_bucket=env.get("S3_BUCKET") or None,
            s3_access_key=env.get("S3_ACCESS_KEY") or None,
            s3_secret_key=env.get("S3_SECRET_KEY") or None,
            s3_region=env.get("S3_REGION") or cls.s3_region,
            attachments_dir=env.get("ATTACHMENTS_DIR") or None,
            max_attachment_bytes=int(env.get("MAX_ATTACHMENT_BYTES") or cls.max_attachment_bytes),
            browserless_url=env.get("BROWSERLESS_URL") or None,
            render_base_url=env.get("RENDER_BASE_URL") or None,
            dev_login=(env.get("DEV_LOGIN") or "") == "1",
        )
