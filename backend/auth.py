import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from slowapi import Limiter
from slowapi.util import get_remote_address

from database import get_db
from models import Signature, MagicToken
from auth_dependencies import create_jwt, get_current_signer, COOKIE_NAME
from email_service import send_magic_link_email

router = APIRouter(prefix="/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)

BASE_URL = os.getenv("BASE_URL", "https://ianua.world")
MAGIC_LINK_EXPIRY_MINUTES = 15
MAGIC_LINK_RATE_LIMIT = 3  # per email per hour


class MagicLinkRequest(BaseModel):
    email: EmailStr


@router.post("/magic-link")
async def send_magic_link(body: MagicLinkRequest, request: Request, db: AsyncSession = Depends(get_db)):
    email = body.email.lower()

    # Check if confirmed signer exists
    result = await db.execute(
        select(Signature).where(Signature.email == email, Signature.confirmed == True)
    )
    signer = result.scalar_one_or_none()

    if not signer:
        # Generic response — no email enumeration
        return {"message": "Si cette adresse est associee a un signataire verifie, un lien vous sera envoye."}

    # Rate limit: 3 magic links per email per hour
    since = datetime.utcnow() - timedelta(hours=1)
    count_result = await db.execute(
        select(func.count(MagicToken.id)).where(
            MagicToken.email == email,
            MagicToken.created_at >= since,
        )
    )
    if count_result.scalar() >= MAGIC_LINK_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many login requests. Try again later.")

    # Create token
    token = uuid.uuid4().hex
    magic_token = MagicToken(
        email=email,
        token=token,
        expires_at=datetime.utcnow() + timedelta(minutes=MAGIC_LINK_EXPIRY_MINUTES),
    )
    db.add(magic_token)
    await db.commit()

    # Send email
    sent = await send_magic_link_email(email, token, signer.lang or "fr")
    if not sent:
        raise HTTPException(status_code=502, detail="Email delivery failed")

    return {"message": "Si cette adresse est associee a un signataire verifie, un lien vous sera envoye."}


@router.get("/verify/{token}")
@limiter.limit("10/minute")
async def verify_magic_link(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(MagicToken).where(MagicToken.token == token)
    )
    magic_token = result.scalar_one_or_none()

    if not magic_token:
        return RedirectResponse(url=f"{BASE_URL}/gouvernance?error=invalid")

    if magic_token.used:
        return RedirectResponse(url=f"{BASE_URL}/gouvernance?error=used")

    now = datetime.utcnow()
    expires = magic_token.expires_at
    if expires.tzinfo is not None:
        expires = expires.replace(tzinfo=None)
    if now > expires:
        return RedirectResponse(url=f"{BASE_URL}/gouvernance?error=expired")

    # Mark token as used
    magic_token.used = True
    await db.commit()

    # Find signer
    signer_result = await db.execute(
        select(Signature).where(Signature.email == magic_token.email, Signature.confirmed == True)
    )
    signer = signer_result.scalar_one_or_none()

    if not signer:
        return RedirectResponse(url=f"{BASE_URL}/gouvernance?error=invalid")

    # Create JWT
    jwt_token = create_jwt(signer_id=signer.id, display_name=signer.pseudo)

    response = RedirectResponse(url=f"{BASE_URL}/gouvernance#deliberation", status_code=307)
    response.set_cookie(
        key=COOKIE_NAME,
        value=jwt_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=24 * 3600,
    )
    return response


@router.get("/me")
async def auth_me(signer: dict = Depends(get_current_signer)):
    """Return current authenticated signer info."""
    return {"sub": signer["sub"], "name": signer["name"]}


@router.post("/logout")
async def logout():
    response = JSONResponse(content={"message": "logged out"})
    response.delete_cookie(key=COOKIE_NAME)
    return response
