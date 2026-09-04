"""
Central application configuration, loaded from environment variables (or a
.env file in development). Keep this module free of heavy imports so it
stays cheap to import from anywhere in the app.
"""
from __future__ import annotations

import secrets
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- General ---
    APP_NAME: str = "MikroTik AI Manager"
    ENVIRONMENT: Literal["development", "production"] = "production"
    HOST: str = "0.0.0.0"
    PORT: int = 8008

    # --- Security ---
    # Used to sign JWTs. MUST be overridden in production via env var.
    SECRET_KEY: str = secrets.token_urlsafe(32)
    # Used to encrypt device credentials / PPPoE secrets at rest (Fernet key,
    # 32 url-safe base64-encoded bytes). If not supplied, one is derived from
    # SECRET_KEY on first boot and persisted to disk so restarts keep working.
    ENCRYPTION_KEY: str | None = None
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 12
    ALGORITHM: str = "HS256"

    # First-run admin account (only used if no users exist yet). You are
    # forced to change this password on first login - see auth.change_password.
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin"

    # --- Database ---
    # Defaults to a local SQLite file so the whole stack runs in one small
    # container. Point this at a Postgres DSN (e.g.
    # postgresql+psycopg://user:pass@host/db) once you outgrow SQLite.
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/app.db"

    # --- Data / file storage ---
    DATA_DIR: str = "./data"
    FIRMWARE_DIR: str = "./data/firmware"
    BACKUP_DIR: str = "./data/backups"

    # --- Polling engine ---
    # How many devices can be polled concurrently. Keep this modest on small
    # VMs (e.g. an Oracle Cloud free-tier instance) - it bounds both CPU and
    # the number of concurrent TCP connections opened to your routers.
    POLL_CONCURRENCY: int = 25
    POLL_INTERVAL_FAST_SECONDS: int = 60      # cpu/mem/signal/ping
    POLL_INTERVAL_FULL_SECONDS: int = 300     # full interface/pppoe/health sweep
    DISCOVERY_INTERVAL_SECONDS: int = 1800    # periodic re-discovery per management router
    METRIC_RETENTION_DAYS: int = 14           # raw samples kept this long
    METRIC_ROLLUP_RETENTION_DAYS: int = 400   # hourly rollups kept this long

    # --- Prediction / AI ---
    ENABLE_ML_ANOMALY_DETECTION: bool = True
    ML_MIN_SAMPLES: int = 50           # minimum history points before ML kicks in for a metric
    ML_RETRAIN_INTERVAL_SECONDS: int = 3600

    ENABLE_LLM_EXPLANATIONS: bool = False
    LLM_PROVIDER: Literal["openai", "anthropic", "none"] = "none"
    LLM_API_KEY: str | None = None
    LLM_MODEL: str = "gpt-4o-mini"

    # --- Notifications (optional, extra feature) ---
    NOTIFY_WEBHOOK_URL: str | None = None
    NOTIFY_TELEGRAM_BOT_TOKEN: str | None = None
    NOTIFY_TELEGRAM_CHAT_ID: str | None = None

    # --- Connectivity test defaults (the "client connectivity test" checklist
    # on a CPE's detail page - see services/connectivity_test_service.py) ---
    PING_TEST_DOMAIN: str = "google.com"
    PING_TEST_COUNT: int = 50
    # Your own internal iperf-style speed-test server, reachable from your
    # CPEs, used for the "/tool bandwidth-test toward internal speed test
    # server" step - leave BANDWIDTH_TEST_TARGET unset to skip that step.
    BANDWIDTH_TEST_TARGET: str | None = None
    BANDWIDTH_TEST_USERNAME: str = "band"
    BANDWIDTH_TEST_PASSWORD: str = "test"
    BANDWIDTH_TEST_DURATION_SECONDS: int = 20

    # --- CORS (only matters if you serve frontend separately) ---
    CORS_ORIGINS: list[str] = ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
