"""Environment-backed application configuration."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass

PRODUCTION_ENVS = frozenset({"production", "staging"})

AGENT_SCOPES = frozenset(
    {
        "pidge:draft",
        "pidge:enrich",
        "pidge:calendar.propose",
        "pidge:notes.pin",
    }
)


@dataclass(frozen=True, slots=True)
class PidgeConfig:
    env: str
    debug: bool
    database_url: str | None
    secret_key: str
    bootstrap_token: str
    public_origin: str | None
    loft_name: str

    @property
    def production(self) -> bool:
        return self.env in PRODUCTION_ENVS

    @classmethod
    def from_env(cls, *, debug: bool = True) -> PidgeConfig:
        env = (os.environ.get("PIDGE_ENV") or "development").strip().lower()
        if env == "prod":
            env = "production"
        database_url = (os.environ.get("DATABASE_URL") or "").strip() or None
        secret_key = (os.environ.get("PIDGE_SECRET_KEY") or "").strip()
        bootstrap_token = (os.environ.get("PIDGE_BOOTSTRAP_TOKEN") or "").strip()
        public_origin = (os.environ.get("PIDGE_PUBLIC_ORIGIN") or "").strip().rstrip("/")
        railway_domain = (os.environ.get("RAILWAY_PUBLIC_DOMAIN") or "").strip()
        if not public_origin and railway_domain:
            public_origin = f"https://{railway_domain}"
        loft_name = (os.environ.get("PIDGE_LOFT_NAME") or "Pidge Loft").strip() or "Pidge Loft"

        if env in PRODUCTION_ENVS:
            if database_url is None:
                raise RuntimeError("DATABASE_URL is required in production.")
            if len(secret_key) < 32:
                raise RuntimeError("PIDGE_SECRET_KEY must be at least 32 characters.")
            if len(bootstrap_token) < 24:
                raise RuntimeError("PIDGE_BOOTSTRAP_TOKEN must be at least 24 characters.")
        else:
            secret_key = secret_key or secrets.token_urlsafe(48)
            bootstrap_token = bootstrap_token or "development-bootstrap-token"

        return cls(
            env=env,
            debug=debug,
            database_url=database_url,
            secret_key=secret_key,
            bootstrap_token=bootstrap_token,
            public_origin=public_origin or None,
            loft_name=loft_name,
        )
