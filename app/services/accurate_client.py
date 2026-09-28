from __future__ import annotations
from datetime import datetime, timedelta
from urllib.parse import urlencode
import httpx
from sqlalchemy.orm import Session
from app.config import settings
from app.models import OAuthCredential, AccurateDatabase
from app.core.security import decrypt_secret, encrypt_secret


class AccurateAPIError(RuntimeError):
    pass


class AccurateOAuthClient:
    def authorization_url(self, state: str) -> str:
        params = {
            "client_id": settings.aol_client_id,
            "response_type": "code",
            "redirect_uri": settings.aol_redirect_uri,
            "scope": settings.aol_scopes,
            "state": state,
        }
        return f"{settings.aol_authorize_url}?{urlencode(params)}"

    def exchange_code(self, code: str) -> dict:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            r = client.post(
                settings.aol_token_url,
                data={"code": code, "grant_type": "authorization_code", "redirect_uri": settings.aol_redirect_uri},
                auth=(settings.aol_client_id, settings.aol_client_secret),
            )
            r.raise_for_status()
            return r.json()

    def refresh(self, credential: OAuthCredential, db: Session) -> OAuthCredential:
        refresh_token = decrypt_secret(credential.refresh_token_enc)
        if not refresh_token:
            raise AccurateAPIError("Refresh token tidak tersedia. Hubungkan ulang Accurate Online.")
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            r = client.post(
                settings.aol_token_url,
                data={"grant_type": "refresh_token", "refresh_token": refresh_token},
                auth=(settings.aol_client_id, settings.aol_client_secret),
            )
            r.raise_for_status()
            data = r.json()
        credential.access_token_enc = encrypt_secret(data["access_token"])
        if data.get("refresh_token"):
            credential.refresh_token_enc = encrypt_secret(data["refresh_token"])
        expires_in = int(data.get("expires_in") or 1295999)
        credential.expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        credential.scope = data.get("scope", credential.scope)
        db.commit()
        return credential


class AccurateClient:
    def __init__(self, access_token: str, session_id: str = "", host: str = ""):
        self.access_token = access_token
        self.session_id = session_id
        self.host = host.rstrip("/")

    @property
    def headers(self) -> dict:
        h = {"Authorization": f"Bearer {self.access_token}"}
        if self.session_id:
            h["X-Session-ID"] = self.session_id
        return h

    def _get(self, url: str, params: dict | None = None) -> dict:
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            r = client.get(url, headers=self.headers, params=params or {})
            if r.status_code == 401:
                raise AccurateAPIError("Access token tidak valid / expired")
            r.raise_for_status()
            data = r.json()
        if data.get("s") is False:
            raise AccurateAPIError(str(data.get("d") or data))
        return data

    def db_list(self) -> list[dict]:
        data = self._get(f"{settings.aol_account_base_url}/api/db-list.do")
        return data.get("d") or []

    def open_db(self, accurate_db_id: int) -> dict:
        return self._get(f"{settings.aol_account_base_url}/api/open-db.do", {"id": accurate_db_id})

    def api_get(self, resource: str, action: str, params: dict | None = None) -> dict:
        if not self.host or not self.session_id:
            raise AccurateAPIError("Database AOL belum di-open")
        return self._get(f"{self.host}/accurate/api/{resource}/{action}.do", params)

    def paged_list(self, resource: str, fields: str = "", page_size: int = 100, extra: dict | None = None):
        page = 1
        while True:
            params = {"sp.page": page, "sp.pageSize": page_size}
            if fields:
                params["fields"] = fields
            if extra:
                params.update(extra)
            data = self.api_get(resource, "list", params)
            rows = data.get("d") or []
            for row in rows:
                yield row
            sp = data.get("sp") or {}
            page_count = int(sp.get("pageCount") or 1)
            if page >= page_count or not rows:
                break
            page += 1


def credential_access_token(credential: OAuthCredential, db: Session) -> str:
    if credential.expires_at and credential.expires_at <= datetime.utcnow() + timedelta(hours=12):
        credential = AccurateOAuthClient().refresh(credential, db)
    return decrypt_secret(credential.access_token_enc)


def client_for_database(dbrow: AccurateDatabase, credential: OAuthCredential, db: Session) -> AccurateClient:
    token = credential_access_token(credential, db)
    return AccurateClient(token, decrypt_secret(dbrow.session_enc), dbrow.host)
