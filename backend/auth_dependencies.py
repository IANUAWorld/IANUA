import os
import jwt
from datetime import datetime, timedelta, timezone
from fastapi import Request, HTTPException

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24
COOKIE_NAME = "ianua_session"


def create_jwt(signer_id: int, display_name: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": signer_id,
        "name": display_name,
        "iat": now,
        "exp": now + timedelta(hours=JWT_EXPIRATION_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


async def get_current_signer(request: Request) -> dict:
    """FastAPI dependency: extract and validate JWT from cookie.
    Returns dict with 'sub' (signer_id) and 'name' (display_name).
    Raises 401 if not authenticated."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_jwt(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return payload


async def get_optional_signer(request: Request) -> dict | None:
    """Like get_current_signer but returns None instead of raising."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return decode_jwt(token)
