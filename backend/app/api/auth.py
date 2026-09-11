import hmac

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.auth import create_token
from app.core.config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


def _constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


@router.post("/login")
async def login(body: LoginRequest):
    valid = _constant_time_eq(body.username, settings.admin_username) and _constant_time_eq(
        body.password, settings.admin_password
    )
    if not valid:
        raise HTTPException(401, "invalid credentials")
    return {"token": create_token(body.username)}
