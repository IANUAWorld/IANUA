import os
import uuid
import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Depends, Request, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, func, case, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from dotenv import load_dotenv

load_dotenv()

from database import get_db, engine, Base, IS_SQLITE, create_tables_sync
from models import Subscriber, Comment, Reaction, Amendment, AmendmentVote
from email_service import send_confirmation_email

# ── App ──────────────────────────────────────────
app = FastAPI(title="Ianua API", version="1.0.0")

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})


# ── CORS ─────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Config ───────────────────────────────────────
ADMIN_KEY = os.getenv("ADMIN_KEY", "changeme_strong_random_key")
BASE_URL = os.getenv("BASE_URL", "https://ianua.world")
VALID_PRINCIPLES = {"I", "II", "III", "IV", "V", "VI", "VII", "VIII"}
VALID_REACTIONS = {"pertinent", "enrichissant", "hors_sujet"}


# ── Helpers ──────────────────────────────────────
def get_fingerprint(request: Request) -> str:
    ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "unknown")
    return hashlib.sha256(f"{ip}{ua}".encode()).hexdigest()


def verify_admin(x_admin_key: str = Header(None)):
    if not x_admin_key or x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


# ── Pydantic models ─────────────────────────────
class SubscribeRequest(BaseModel):
    email: EmailStr
    lang: str = "fr"


class CommentRequest(BaseModel):
    principle_id: str
    author_name: str
    author_country: str | None = None
    content: str
    lang: str = "fr"


class ReactionRequest(BaseModel):
    comment_id: int
    reaction_type: str


# ── Startup ──────────────────────────────────────
@app.on_event("startup")
async def startup():
    if IS_SQLITE:
        # Dev: create tables directly
        create_tables_sync()
    else:
        # Prod: run Alembic migrations
        import subprocess
        subprocess.run(["alembic", "upgrade", "head"], check=True)


# ── PUBLIC ENDPOINTS ─────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/stats")
async def stats(db: AsyncSession = Depends(get_db)):
    subscribers = await db.execute(select(func.count()).where(Subscriber.confirmed == True))
    comments = await db.execute(select(func.count()).where(Comment.status == "approved"))
    return {
        "subscribers": subscribers.scalar() or 0,
        "comments": comments.scalar() or 0
    }


@app.post("/subscribe")
async def subscribe(body: SubscribeRequest, db: AsyncSession = Depends(get_db)):
    lang = body.lang if body.lang in ("fr", "en", "es") else "en"

    # Check if already confirmed
    result = await db.execute(
        select(Subscriber).where(Subscriber.email == body.email)
    )
    existing = result.scalar_one_or_none()

    if existing and existing.confirmed:
        # Don't reveal email exists — return 200
        return {"message": "ok"}

    if existing and not existing.confirmed:
        # Resend confirmation with new token
        token = uuid.uuid4().hex
        existing.token = token
        existing.lang = lang
        await db.commit()
        await send_confirmation_email(body.email, token, lang)
        return {"message": "ok"}

    # New subscriber
    token = uuid.uuid4().hex
    subscriber = Subscriber(email=body.email, lang=lang, token=token)
    db.add(subscriber)
    await db.commit()
    await send_confirmation_email(body.email, token, lang)
    return {"message": "ok"}


@app.get("/confirm/{token}")
async def confirm(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Subscriber).where(Subscriber.token == token)
    )
    subscriber = result.scalar_one_or_none()

    if not subscriber:
        return RedirectResponse(url=f"{BASE_URL}/confirmed.html?lang=en&error=invalid")

    # Check 72h expiry
    if subscriber.created_at:
        created = subscriber.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if datetime.utcnow() - created > timedelta(hours=72):
            return RedirectResponse(url=f"{BASE_URL}/confirmed.html?lang={subscriber.lang}&error=expired")

    subscriber.confirmed = True
    subscriber.confirmed_at = datetime.utcnow()
    await db.commit()

    return RedirectResponse(url=f"{BASE_URL}/confirmed.html?lang={subscriber.lang}")


@app.get("/unsubscribe/{token}")
async def unsubscribe(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Subscriber).where(Subscriber.token == token)
    )
    subscriber = result.scalar_one_or_none()

    if subscriber:
        await db.delete(subscriber)
        await db.commit()

    # Always redirect regardless — don't reveal if token existed
    return RedirectResponse(url=f"{BASE_URL}/?unsubscribed=true")


@app.get("/comments/{principle_id}")
async def get_comments(principle_id: str, db: AsyncSession = Depends(get_db)):
    if principle_id not in VALID_PRINCIPLES:
        raise HTTPException(status_code=400, detail="Invalid principle_id")

    # Get approved comments with reaction counts
    stmt = (
        select(
            Comment.id,
            Comment.author_name,
            Comment.author_country,
            Comment.content,
            Comment.lang,
            Comment.created_at,
            func.coalesce(
                func.sum(case((Reaction.reaction_type == "pertinent", 1), else_=0)), 0
            ).label("pertinent"),
            func.coalesce(
                func.sum(case((Reaction.reaction_type == "enrichissant", 1), else_=0)), 0
            ).label("enrichissant"),
            func.coalesce(
                func.sum(case((Reaction.reaction_type == "hors_sujet", 1), else_=0)), 0
            ).label("hors_sujet"),
        )
        .outerjoin(Reaction, Reaction.comment_id == Comment.id)
        .where(Comment.principle_id == principle_id, Comment.status == "approved")
        .group_by(Comment.id)
        .order_by(
            (
                func.coalesce(func.sum(case((Reaction.reaction_type == "pertinent", 1), else_=0)), 0)
                + func.coalesce(func.sum(case((Reaction.reaction_type == "enrichissant", 1), else_=0)), 0)
                - func.coalesce(func.sum(case((Reaction.reaction_type == "hors_sujet", 1), else_=0)), 0)
            ).desc()
        )
    )

    result = await db.execute(stmt)
    rows = result.all()

    comments = [
        {
            "id": r.id,
            "author_name": r.author_name,
            "author_country": r.author_country,
            "content": r.content,
            "lang": r.lang,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "reactions": {
                "pertinent": r.pertinent,
                "enrichissant": r.enrichissant,
                "hors_sujet": r.hors_sujet,
            },
        }
        for r in rows
    ]

    return {"comments": comments}


@app.post("/comments")
@limiter.limit("3/day", key_func=get_remote_address)
async def post_comment(
    body: CommentRequest, request: Request, db: AsyncSession = Depends(get_db)
):
    if body.principle_id not in VALID_PRINCIPLES:
        raise HTTPException(status_code=400, detail="Invalid principle_id")

    if not body.author_name.strip() or not body.content.strip():
        raise HTTPException(status_code=400, detail="Name and content required")

    if len(body.content) > 2000:
        raise HTTPException(status_code=400, detail="Content too long (max 2000)")

    fingerprint = get_fingerprint(request)

    # Check rate limit: 3 comments per fingerprint per 24h
    since = datetime.utcnow() - timedelta(hours=24)
    result = await db.execute(
        select(func.count(Comment.id)).where(
            Comment.fingerprint == fingerprint,
            Comment.created_at >= since,
        )
    )
    count = result.scalar()
    if count >= 3:
        raise HTTPException(status_code=429, detail="Rate limit: 3 comments per 24h")

    lang = body.lang if body.lang in ("fr", "en", "es") else "fr"

    comment = Comment(
        principle_id=body.principle_id,
        author_name=body.author_name.strip(),
        author_country=body.author_country.strip() if body.author_country else None,
        content=body.content.strip(),
        lang=lang,
        fingerprint=fingerprint,
    )
    db.add(comment)
    await db.commit()

    return {"message": "pending"}


@app.post("/reactions")
@limiter.limit("30/hour", key_func=get_remote_address)
async def post_reaction(
    body: ReactionRequest, request: Request, db: AsyncSession = Depends(get_db)
):
    if body.reaction_type not in VALID_REACTIONS:
        raise HTTPException(status_code=400, detail="Invalid reaction_type")

    # Verify comment exists
    result = await db.execute(
        select(Comment.id).where(Comment.id == body.comment_id, Comment.status == "approved")
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Comment not found")

    fingerprint = get_fingerprint(request)

    # Check rate limit: 30 reactions per fingerprint per hour
    since = datetime.utcnow() - timedelta(hours=1)
    result = await db.execute(
        select(func.count(Reaction.id)).where(
            Reaction.fingerprint == fingerprint,
            Reaction.created_at >= since,
        )
    )
    count = result.scalar()
    if count >= 30:
        raise HTTPException(status_code=429, detail="Rate limit: 30 reactions per hour")

    # Toggle: if reaction exists, remove it; if not, add it
    existing = await db.execute(
        select(Reaction).where(
            Reaction.comment_id == body.comment_id,
            Reaction.reaction_type == body.reaction_type,
            Reaction.fingerprint == fingerprint,
        )
    )
    existing_reaction = existing.scalar_one_or_none()

    if existing_reaction:
        await db.delete(existing_reaction)
        await db.commit()
        return {"message": "removed"}

    reaction = Reaction(
        comment_id=body.comment_id,
        reaction_type=body.reaction_type,
        fingerprint=fingerprint,
    )
    db.add(reaction)
    await db.commit()

    return {"message": "added"}


# ── GOVERNANCE ENDPOINTS ─────────────────────────

@app.get("/amendments")
async def list_amendments(
    status: str | None = None,
    principle_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List all public amendments, optionally filtered by status or principle."""
    stmt = select(Amendment).where(
        Amendment.status.in_(["deliberation", "accepted", "ratified", "rejected"])
    )
    if status:
        stmt = select(Amendment).where(Amendment.status == status)
    if principle_id:
        stmt = stmt.where(Amendment.principle_id == principle_id)
    stmt = stmt.order_by(Amendment.proposed_at.desc())

    result = await db.execute(stmt)
    amendments = result.scalars().all()

    return {
        "amendments": [
            {
                "code": a.code,
                "principle_id": a.principle_id,
                "target": a.target,
                "amendment_type": a.amendment_type,
                "text_before": a.text_before,
                "text_after": a.text_after,
                "motivation": a.motivation,
                "motivation_en": a.motivation_en,
                "motivation_es": a.motivation_es,
                "text_after_en": a.text_after_en,
                "text_after_es": a.text_after_es,
                "inspiration": a.inspiration,
                "source_type": a.source_type,
                "proposed_by": a.proposed_by,
                "phase": a.phase,
                "status": a.status,
                "ratified_by": a.ratified_by,
                "ratified_at": a.ratified_at.isoformat() if a.ratified_at else None,
                "proposed_at": a.proposed_at.isoformat() if a.proposed_at else None,
                "published_at": a.published_at.isoformat() if a.published_at else None,
                "charte_version": a.charte_version,
                "github_commit": a.github_commit,
                "votes_for": a.votes_for,
                "votes_against": a.votes_against,
                "votes_abstain": a.votes_abstain,
            }
            for a in amendments
        ]
    }


@app.get("/amendments/{code}")
async def get_amendment(code: str, db: AsyncSession = Depends(get_db)):
    """Get a single amendment by code."""
    result = await db.execute(select(Amendment).where(Amendment.code == code))
    a = result.scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=404, detail="Amendment not found")

    return {
        "code": a.code,
        "principle_id": a.principle_id,
        "target": a.target,
        "amendment_type": a.amendment_type,
        "text_before": a.text_before,
        "text_after": a.text_after,
        "motivation": a.motivation,
        "motivation_en": a.motivation_en,
        "motivation_es": a.motivation_es,
        "text_after_en": a.text_after_en,
        "text_after_es": a.text_after_es,
        "inspiration": a.inspiration,
        "source_type": a.source_type,
        "proposed_by": a.proposed_by,
        "phase": a.phase,
        "status": a.status,
        "ratified_by": a.ratified_by,
        "ratified_at": a.ratified_at.isoformat() if a.ratified_at else None,
        "proposed_at": a.proposed_at.isoformat() if a.proposed_at else None,
        "published_at": a.published_at.isoformat() if a.published_at else None,
        "charte_version": a.charte_version,
        "github_commit": a.github_commit,
        "votes_for": a.votes_for,
        "votes_against": a.votes_against,
        "votes_abstain": a.votes_abstain,
    }


@app.get("/governance/stats")
async def governance_stats(db: AsyncSession = Depends(get_db)):
    """Global governance statistics."""
    ratified = await db.execute(
        select(func.count()).select_from(Amendment).where(Amendment.status == "ratified")
    )
    deliberation = await db.execute(
        select(func.count()).select_from(Amendment).where(Amendment.status == "deliberation")
    )
    # Get latest charte version
    latest = await db.execute(
        select(Amendment.charte_version)
        .where(Amendment.status == "ratified", Amendment.charte_version.isnot(None))
        .order_by(Amendment.ratified_at.desc())
        .limit(1)
    )
    version = latest.scalar_one_or_none() or "v1.0"

    return {
        "charte_version": version,
        "amendments_ratified": ratified.scalar() or 0,
        "amendments_deliberation": deliberation.scalar() or 0,
        "last_updated": "2026-03-10",
    }


# ── ADMIN ENDPOINTS ──────────────────────────────

@app.get("/admin/comments")
async def admin_list_comments(
    status: str = "pending",
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
):
    result = await db.execute(
        select(Comment)
        .where(Comment.status == status)
        .order_by(Comment.created_at.desc())
    )
    comments = result.scalars().all()

    return {
        "comments": [
            {
                "id": c.id,
                "principle_id": c.principle_id,
                "author_name": c.author_name,
                "author_country": c.author_country,
                "content": c.content,
                "lang": c.lang,
                "status": c.status,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in comments
        ]
    }


@app.post("/admin/comments/{comment_id}/approve")
async def admin_approve(
    comment_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
):
    result = await db.execute(select(Comment).where(Comment.id == comment_id))
    comment = result.scalar_one_or_none()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    comment.status = "approved"
    comment.approved_at = datetime.utcnow()
    await db.commit()
    return {"message": "approved"}


@app.post("/admin/comments/{comment_id}/reject")
async def admin_reject(
    comment_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
):
    result = await db.execute(select(Comment).where(Comment.id == comment_id))
    comment = result.scalar_one_or_none()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    comment.status = "rejected"
    await db.commit()
    return {"message": "rejected"}


@app.get("/admin/subscribers")
async def admin_subscribers(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
):
    result = await db.execute(
        select(Subscriber)
        .where(Subscriber.confirmed == True)
        .order_by(Subscriber.confirmed_at.desc())
    )
    subscribers = result.scalars().all()

    return {
        "subscribers": [
            {
                "id": s.id,
                "email": s.email,
                "lang": s.lang,
                "confirmed_at": s.confirmed_at.isoformat() if s.confirmed_at else None,
            }
            for s in subscribers
        ]
    }
