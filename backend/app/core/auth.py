import base64
import hashlib
import hmac
import json
import time

from fastapi import Header, HTTPException

from app.core.config import settings

TOKEN_TTL_SECONDS = 12 * 60 * 60


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_token(username: str) -> str:
    """Minimal signed session token (HMAC-SHA256 over a JSON payload) --
    no extra dependency needed for a single-admin panel. Not meant to
    replace a real user system if this ever grows multiple accounts or
    roles."""
    payload = {"sub": username, "exp": int(time.time()) + TOKEN_TTL_SECONDS}
    payload_b64 = _b64encode(json.dumps(payload).encode())
    signature = hmac.new(settings.secret_key.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def verify_token(token: str) -> str:
    try:
        payload_b64, signature = token.split(".", 1)
        expected = hmac.new(settings.secret_key.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("bad signature")
        payload = json.loads(_b64decode(payload_b64))
        if payload["exp"] < time.time():
            raise ValueError("expired")
        return payload["sub"]
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("invalid token") from exc


async def require_admin(authorization: str | None = Header(default=None)) -> str:
    """FastAPI dependency guarding every admin-only (write) endpoint. The
    public arena/OBS source never authenticates -- only the admin panel's
    create/update/delete/simulate/live-connect actions go through this."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization.removeprefix("Bearer ")
    try:
        return verify_token(token)
    except ValueError:
        raise HTTPException(401, "invalid or expired token")
