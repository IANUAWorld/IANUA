import os
import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Amendment, MagicToken, Signature

router = APIRouter(prefix="/crons", tags=["crons"])

ADMIN_KEY = os.getenv("ADMIN_KEY", "")


def verify_admin(x_admin_key: str = Header(None)):
    if not x_admin_key or not ADMIN_KEY or not hmac.compare_digest(x_admin_key, ADMIN_KEY):
        raise HTTPException(status_code=403, detail="Forbidden")


TIER_THRESHOLDS = {
    "mineur": 0.50,
    "substantiel": 2 / 3,
    "fondateur": 2 / 3,
}


@router.post("/expire-proposals")
async def expire_proposals(
    db: AsyncSession = Depends(get_db),
    _admin: None = Depends(verify_admin),
):
    now = datetime.utcnow()
    result = await db.execute(
        select(Amendment).where(
            Amendment.status == "proposed",
            Amendment.expires_at <= now,
        )
    )
    amendments = result.scalars().all()
    for a in amendments:
        a.status = "expired"
    await db.commit()
    return {"count": len(amendments)}


@router.post("/close-votes")
async def close_votes(
    db: AsyncSession = Depends(get_db),
    _admin: None = Depends(verify_admin),
):
    now = datetime.utcnow()
    result = await db.execute(
        select(Amendment).where(
            Amendment.status == "deliberation",
            Amendment.vote_closed_at <= now,
        )
    )
    amendments = result.scalars().all()

    # Count confirmed signatories (for quorum calculation)
    sig_count_result = await db.execute(
        select(func.count()).select_from(Signature).where(Signature.confirmed == True)
    )
    confirmed_signatories = sig_count_result.scalar()

    results = []
    for a in amendments:
        votes_for = a.votes_for or 0
        votes_against = a.votes_against or 0
        votes_abstain = a.votes_abstain or 0
        total_votes = votes_for + votes_against + votes_abstain

        tier = a.tier or "mineur"
        threshold = TIER_THRESHOLDS.get(tier, 0.50)

        # Check quorum for fondateur tier
        if tier == "fondateur":
            quorum_required = 0.3 * confirmed_signatories
            if total_votes < quorum_required:
                a.status = "rejected"
                a.rejected_reason = "quorum_not_met"
                results.append({"code": a.code, "status": "rejected", "reason": "quorum_not_met"})
                continue

        # Calculate majority: FOR / (FOR + AGAINST)
        decisive_votes = votes_for + votes_against
        if decisive_votes == 0:
            a.status = "rejected"
            results.append({"code": a.code, "status": "rejected", "reason": "no_decisive_votes"})
            continue

        majority = votes_for / decisive_votes
        if majority >= threshold:
            a.status = "ratified"
            a.ratified_at = now
            results.append({"code": a.code, "status": "ratified", "majority": majority})
        else:
            a.status = "rejected"
            results.append({"code": a.code, "status": "rejected", "majority": majority})

    await db.commit()
    return {"count": len(amendments), "results": results}


@router.post("/cleanup-tokens")
async def cleanup_tokens(
    db: AsyncSession = Depends(get_db),
    _admin: None = Depends(verify_admin),
):
    now = datetime.utcnow()
    result = await db.execute(
        delete(MagicToken).where(
            (MagicToken.used == True) | (MagicToken.expires_at < now)
        )
    )
    await db.commit()
    return {"count": result.rowcount}
