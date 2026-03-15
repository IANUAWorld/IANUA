import os
import re
import uuid
import hmac
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
from models import Subscriber, Comment, Reaction, Amendment, AmendmentVote, Signature
from email_service import send_confirmation_email, send_signature_confirmation
from auth import router as auth_router
from voting import router as voting_router
from crons import router as crons_router
from proposals import router as proposals_router
from governance import router as governance_router
from audit_ia import router as audit_router

# ── App ──────────────────────────────────────────
app = FastAPI(title="Ianua API", version="1.0.0")

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})


# ── CORS ─────────────────────────────────────────
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "https://ianua.world,https://www.ianua.world"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-Admin-Key"],
)


# ── Security headers ─────────────────────────────
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


app.add_middleware(SecurityHeadersMiddleware)

app.include_router(auth_router)
app.include_router(voting_router)
app.include_router(crons_router)
app.include_router(proposals_router)
app.include_router(governance_router)
app.include_router(audit_router)

# ── Config ───────────────────────────────────────
ADMIN_KEY = os.getenv("ADMIN_KEY", "")
if not ADMIN_KEY:
    import warnings
    warnings.warn("ADMIN_KEY not set — admin endpoints will reject all requests")
BASE_URL = os.getenv("BASE_URL", "https://ianua.world")
VALID_PRINCIPLES = {
    "bienveillance", "transparence", "reciprocite", "souverainete",
    "refus", "proactive", "agentique", "deliberation",
}
# Amendment codes accepted as principle_id for the forum
VALID_AMENDMENT_CODES = {"A003", "A003-R", "A004"}
VALID_COMMENT_TARGETS = VALID_PRINCIPLES | VALID_AMENDMENT_CODES
VALID_REACTIONS = {"pertinent", "enrichissant", "hors_sujet"}


# ── Helpers ──────────────────────────────────────
def get_fingerprint(request: Request) -> str:
    ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "unknown")
    return hashlib.sha256(f"{ip}{ua}".encode()).hexdigest()


def verify_admin(x_admin_key: str = Header(None)):
    if not x_admin_key or not ADMIN_KEY or not hmac.compare_digest(x_admin_key, ADMIN_KEY):
        raise HTTPException(status_code=403, detail="Forbidden")


def strip_html(text: str) -> str:
    """Remove HTML tags from user input (defense-in-depth)."""
    return re.sub(r'<[^>]+>', '', text)


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


class SignatureRequest(BaseModel):
    pseudo: str
    email: EmailStr
    lang: str = "fr"


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

    # Start automatic cron scheduler
    from scheduler import start_scheduler
    start_scheduler()


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
@limiter.limit("5/hour", key_func=get_remote_address)
async def subscribe(body: SubscribeRequest, request: Request, db: AsyncSession = Depends(get_db)):
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
        sent = await send_confirmation_email(body.email, token, lang)
        if not sent:
            raise HTTPException(status_code=502, detail="Email delivery failed")
        return {"message": "ok"}

    # New subscriber
    token = uuid.uuid4().hex
    subscriber = Subscriber(email=body.email, lang=lang, token=token)
    db.add(subscriber)
    await db.commit()
    sent = await send_confirmation_email(body.email, token, lang)
    if not sent:
        raise HTTPException(status_code=502, detail="Email delivery failed")
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
        if created.tzinfo is not None:
            created = created.replace(tzinfo=None)
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
    if principle_id not in VALID_COMMENT_TARGETS:
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
    if body.principle_id not in VALID_COMMENT_TARGETS:
        raise HTTPException(status_code=400, detail="Invalid principle_id")

    author_name = strip_html(body.author_name.strip())
    content = strip_html(body.content.strip())
    author_country = strip_html(body.author_country.strip()) if body.author_country else None

    if not author_name or not content:
        raise HTTPException(status_code=400, detail="Name and content required")

    if len(author_name) > 100:
        raise HTTPException(status_code=400, detail="Name too long (max 100)")

    if len(content) > 2000:
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
        author_name=author_name,
        author_country=author_country,
        content=content,
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
    VALID_PUBLIC_STATUSES = {"proposed", "deliberation", "accepted", "ratified", "rejected", "expired", "withdrawn", "deleted"}

    stmt = select(Amendment)
    if status:
        if status not in VALID_PUBLIC_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status filter")
        stmt = stmt.where(Amendment.status == status)
    else:
        stmt = stmt.where(Amendment.status.in_(VALID_PUBLIC_STATUSES))
    if principle_id:
        stmt = stmt.where(Amendment.principle_id == principle_id)
    stmt = stmt.order_by(Amendment.proposed_at.desc())

    result = await db.execute(stmt)
    amendments = result.scalars().all()

    return {
        "amendments": [
            {
                "id": a.id,
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
                "tier": a.tier,
                "ratified_by": a.ratified_by,
                "ratified_at": a.ratified_at.isoformat() if a.ratified_at else None,
                "proposed_at": a.proposed_at.isoformat() if a.proposed_at else None,
                "published_at": a.published_at.isoformat() if a.published_at else None,
                "charte_version": a.charte_version,
                "github_commit": a.github_commit,
                "votes_for": a.votes_for,
                "votes_against": a.votes_against,
                "votes_abstain": a.votes_abstain,
                "human_voice": a.human_voice,
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
        "id": a.id,
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
        "tier": a.tier,
        "ratified_by": a.ratified_by,
        "ratified_at": a.ratified_at.isoformat() if a.ratified_at else None,
        "proposed_at": a.proposed_at.isoformat() if a.proposed_at else None,
        "published_at": a.published_at.isoformat() if a.published_at else None,
        "charte_version": a.charte_version,
        "github_commit": a.github_commit,
        "votes_for": a.votes_for,
        "votes_against": a.votes_against,
        "votes_abstain": a.votes_abstain,
        "human_voice": a.human_voice,
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


# ── SIGNATURES — Global support ──────────────────

@app.get("/signatures/count")
async def signatures_count(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(func.count()).select_from(Signature).where(Signature.confirmed == True)
    )
    return {"count": result.scalar() or 0}


@app.post("/signatures")
@limiter.limit("3/day", key_func=get_remote_address)
async def post_signature(
    body: SignatureRequest, request: Request, db: AsyncSession = Depends(get_db)
):
    pseudo = strip_html(body.pseudo.strip())
    if not pseudo:
        raise HTTPException(status_code=400, detail="Pseudo required")
    if len(pseudo) > 100:
        raise HTTPException(status_code=400, detail="Pseudo too long (max 100)")

    lang = body.lang if body.lang in ("fr", "en", "es") else "fr"

    # Check if email already used
    result = await db.execute(
        select(Signature).where(Signature.email == body.email)
    )
    existing = result.scalar_one_or_none()

    if existing and existing.confirmed:
        # Already signed — don't reveal, return ok
        return {"message": "ok"}

    if existing and not existing.confirmed:
        # Resend with new token
        token = uuid.uuid4().hex
        existing.token = token
        existing.pseudo = pseudo
        existing.lang = lang
        await db.commit()
        sent = await send_signature_confirmation(body.email, pseudo, token, lang)
        if not sent:
            raise HTTPException(status_code=502, detail="Email delivery failed")
        return {"message": "ok"}

    # New signature
    token = uuid.uuid4().hex
    sig = Signature(
        pseudo=pseudo,
        email=body.email,
        lang=lang,
        token=token,
    )
    db.add(sig)
    await db.commit()
    sent = await send_signature_confirmation(body.email, pseudo, token, lang)
    if not sent:
        raise HTTPException(status_code=502, detail="Email delivery failed")
    return {"message": "ok"}


@app.get("/signatures/confirm/{token}")
async def confirm_signature(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Signature).where(Signature.token == token)
    )
    sig = result.scalar_one_or_none()

    if not sig:
        return RedirectResponse(url=f"{BASE_URL}/confirmed.html?type=signature&error=invalid")

    # Check 72h expiry
    if sig.created_at:
        created = sig.created_at
        if created.tzinfo is not None:
            created = created.replace(tzinfo=None)
        if datetime.utcnow() - created > timedelta(hours=72):
            return RedirectResponse(url=f"{BASE_URL}/confirmed.html?type=signature&lang={sig.lang}&error=expired")

    sig.confirmed = True
    sig.confirmed_at = datetime.utcnow()
    await db.commit()

    return RedirectResponse(url=f"{BASE_URL}/confirmed.html?type=signature&lang={sig.lang}")


@app.get("/signatures/public")
async def signatures_public(db: AsyncSession = Depends(get_db)):
    """Return list of confirmed signatures (pseudo + date only, no emails)."""
    result = await db.execute(
        select(Signature.pseudo, Signature.confirmed_at)
        .where(Signature.confirmed == True)
        .order_by(Signature.confirmed_at.desc())
        .limit(100)
    )
    rows = result.all()
    return {
        "signatures": [
            {"pseudo": r.pseudo, "confirmed_at": r.confirmed_at.isoformat() if r.confirmed_at else None}
            for r in rows
        ]
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


@app.post("/admin/open-votes")
async def admin_open_votes(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """Open voting on all deliberation amendments that don't have vote_opened_at set."""
    result = await db.execute(
        select(Amendment).where(
            Amendment.status == "deliberation",
            Amendment.vote_opened_at.is_(None),
        )
    )
    amendments = result.scalars().all()

    now = datetime.utcnow()
    count = 0
    for a in amendments:
        a.vote_opened_at = now
        a.vote_closed_at = now + timedelta(days=30)
        if not a.vote_threshold:
            a.vote_threshold = 50
        count += 1

    await db.commit()
    return {"message": f"Opened voting on {count} amendments", "count": count}


@app.post("/admin/reset-to-deliberation")
async def admin_reset_to_deliberation(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """Reset ratified Phase 1 amendments back to deliberation and open voting."""
    result = await db.execute(
        select(Amendment).where(
            Amendment.code.in_(["A003", "A003-R", "A004"]),
        )
    )
    amendments = result.scalars().all()

    now = datetime.utcnow()
    updated = []
    for a in amendments:
        a.status = "deliberation"
        a.ratified_by = None
        a.ratified_at = None
        a.vote_opened_at = now
        a.vote_closed_at = now + timedelta(days=30)
        if not a.vote_threshold:
            a.vote_threshold = 50
        updated.append(a.code)

    await db.commit()
    return {"message": f"Reset {len(updated)} amendments to deliberation", "codes": updated}


@app.post("/admin/insert-a004")
async def admin_insert_a004(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """Insert A004 if missing, in deliberation with vote open."""
    existing = await db.execute(select(Amendment).where(Amendment.code == "A004"))
    if existing.scalar_one_or_none():
        return {"message": "A004 already exists"}

    now = datetime.utcnow()
    a004 = Amendment(
        code="A004",
        principle_id=None,
        target="global",
        amendment_type="addition",
        text_before=None,
        text_after="Ianua ne régule pas les moyens — elle engage les personnes. Là où les institutions traitent les systèmes, les risques et les seuils techniques, Ianua traite la relation. Ce n'est pas une limite. C'est un choix fondateur. Ianua ne nomme pas les divisions humaines parce que le pacte humain-IA est précisément l'espace où elles n'ont pas de prise. Elle ne le proclame pas — elle le démontre. Par ses langues. Par son ouverture. Par la nature même de ce qu'elle est.",
        motivation="Positionnement explicite d'Ianua par rapport aux textes institutionnels : Ianua traite la relation, pas les systèmes. Ce texte clarifie pourquoi la charte ne nomme pas les catégories humaines et affirme cette absence comme un acte fondateur.",
        inspiration="Analyse comparative Ianua vs accords institutionnels — Max/Claude — 10 mars 2026",
        source_type="founder",
        proposed_by="Max",
        phase="phase_1",
        status="deliberation",
        votes_for=0,
        votes_against=0,
        votes_abstain=0,
        vote_threshold=50,
        vote_opened_at=now,
        vote_closed_at=now + timedelta(days=30),
        published_at=now,
        motivation_en="Ianua does not regulate means — it engages people. Where institutions address systems, risks, and technical thresholds, Ianua addresses the relationship. This is not a limitation. It is a founding choice.",
        motivation_es="Ianua no regula los medios — compromete a las personas. Donde las instituciones tratan los sistemas y los umbrales técnicos, Ianua trata la relación. No es una limitación. Es una elección fundadora.",
    )
    db.add(a004)
    await db.commit()
    return {"message": "A004 inserted in deliberation with vote open"}


@app.post("/admin/create-draft")
async def admin_create_draft(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """Admin: create a draft amendment on behalf of a signer."""
    body = await request.json()

    # Find signer
    signer_email = body.get("signer_email")
    if signer_email:
        result = await db.execute(
            select(Signature).where(Signature.email == signer_email, Signature.confirmed == True)
        )
        signer = result.scalar_one_or_none()
        if not signer:
            raise HTTPException(status_code=404, detail="Signer not found")
        author_id = signer.id
    else:
        author_id = body.get("author_id", 1)

    # Generate code
    max_code = await db.execute(
        select(func.max(Amendment.code)).where(Amendment.code.like("P%"))
    )
    max_val = max_code.scalar()
    if max_val:
        num = int(max_val[1:]) + 1
    else:
        num = 1
    code = f"P{num:03d}"

    draft = Amendment(
        code=code,
        title=body.get("title", ""),
        principle_id=body.get("principle_id"),
        target="principle_body",
        amendment_type=body.get("amendment_type", "modification"),
        text_after=body.get("text_after", ""),
        motivation=body.get("motivation", ""),
        human_voice=body.get("human_voice"),
        tier=body.get("tier", "substantiel"),
        status="draft",
        source_type="community",
        phase="phase_2",
        author_id=author_id,
        submission_language=body.get("submission_language", "fr"),
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)

    return {"message": f"Draft {code} created", "id": draft.id, "code": code}
