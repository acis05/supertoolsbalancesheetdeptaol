from __future__ import annotations
import os
from dataclasses import dataclass


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "SUPERTOOLS BALANCE SHEET DEPARTEMENT/PROJECT AOL")
    app_env: str = os.getenv("APP_ENV", "development")
    app_base_url: str = os.getenv("APP_BASE_URL", "http://localhost:8000").rstrip("/")
    secret_key: str = os.getenv("SECRET_KEY", "dev-secret-change-me")
    token_encryption_key: str = os.getenv("TOKEN_ENCRYPTION_KEY", "")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./supertools_aol.sqlite3")
    cookie_secure: bool = _bool("COOKIE_SECURE", False)

    admin_email: str = os.getenv("ADMIN_EMAIL", "admin@example.com").lower()
    admin_password: str = os.getenv("ADMIN_PASSWORD", "ChangeThisAdminPassword123!")

    aol_client_id: str = os.getenv("AOL_CLIENT_ID", "")
    aol_client_secret: str = os.getenv("AOL_CLIENT_SECRET", "")
    aol_redirect_uri: str = os.getenv("AOL_REDIRECT_URI", "http://localhost:8000/accurate/oauth/callback")
    aol_scopes: str = os.getenv("AOL_SCOPES", "glaccount_view department_view project_view journal_voucher_view")
    aol_authorize_url: str = os.getenv("AOL_AUTHORIZE_URL", "https://account.accurate.id/oauth/authorize")
    aol_token_url: str = os.getenv("AOL_TOKEN_URL", "https://account.accurate.id/oauth/token")
    aol_account_base_url: str = os.getenv("AOL_ACCOUNT_BASE_URL", "https://account.accurate.id").rstrip("/")

    trial_days: int = int(os.getenv("TRIAL_DAYS", "7"))
    trial_max_databases: int = int(os.getenv("TRIAL_MAX_DATABASES", "1"))
    active_max_databases: int = int(os.getenv("ACTIVE_MAX_DATABASES", "5"))


settings = Settings()
