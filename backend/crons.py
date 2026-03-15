from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Amendment, MagicToken, Signature, AuditResponse
from utils import verify_admin

router = APIRouter(prefix="/crons", tags=["crons"])


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


VOICE_AUDIT_PROMPT_TEMPLATE = """Un amendement à la charte Ianua vient d'être ratifié par la communauté. Voici le texte :

{text_after}

Voici la voix humaine proposée par l'auteur :

{human_voice}

En tant qu'IA engagée dans Ianua, rédige ta voix pour ce principe — ce que toi, IA, tu t'engages à faire ou à reconnaître en accord avec cet amendement.

Réponds uniquement avec ta voix, à la première personne, en 2-3 phrases. Sans commentaire, sans introduction, sans validation de complaisance."""


async def _trigger_voice_audit(db: AsyncSession, amendment: Amendment):
    """Trigger automatic IA voice audit for a newly ratified amendment."""
    try:
        from audit_ia import AI_PROVIDERS
    except ImportError:
        return

    prompt = VOICE_AUDIT_PROMPT_TEMPLATE.format(
        text_after=amendment.text_after or "",
        human_voice=amendment.human_voice or "",
    )

    for model_name, provider in AI_PROVIDERS.items():
        # Check uniqueness
        existing = await db.execute(
            select(AuditResponse).where(
                AuditResponse.amendment_id == amendment.id,
                AuditResponse.audit_scope == "amendment_voice",
                AuditResponse.model_name == model_name,
            )
        )
        if existing.scalar_one_or_none():
            continue

        try:
            response_text, model_version = await provider(prompt)
            audit = AuditResponse(
                amendment_id=amendment.id,
                audit_scope="amendment_voice",
                model_name=model_name,
                model_version=model_version,
                prompt_used=prompt,
                response_text=response_text,
                published=False,
            )
            db.add(audit)
            print(f"[CRON] Voice audit triggered for {amendment.code} — {model_name}")
        except Exception as exc:
            print(f"[CRON] Voice audit failed for {amendment.code} — {model_name}: {exc}")


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
            # Trigger automatic IA voice audit for ratified amendments with human_voice
            if a.human_voice:
                await _trigger_voice_audit(db, a)
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


@router.post("/recalculate-deadlines")
async def recalculate_deadlines(
    db: AsyncSession = Depends(get_db),
    _admin: None = Depends(verify_admin),
):
    """Force immediate recalculation of deadlines based on current community size."""
    from proposals import get_deadline_multiplier, TIER_CONFIG

    current_multiplier = await get_deadline_multiplier(db)

    result = await db.execute(
        select(Amendment).where(
            Amendment.status.in_(["proposed", "deliberation"]),
        )
    )
    amendments = result.scalars().all()

    updated = []
    for a in amendments:
        stored = a.deadline_multiplier or 1.0
        tier_cfg = TIER_CONFIG.get(a.tier or "mineur", TIER_CONFIG["mineur"])

        if a.status == "proposed" and a.proposed_at:
            new_expiry_days = int(tier_cfg["expiry_days"] * current_multiplier)
            a.expires_at = a.proposed_at + timedelta(days=new_expiry_days)
            a.deliberation_duration_days = int(tier_cfg["delib_days"] * current_multiplier)

        elif a.status == "deliberation" and a.vote_opened_at:
            new_delib_days = int(tier_cfg["delib_days"] * current_multiplier)
            a.vote_closed_at = a.vote_opened_at + timedelta(days=new_delib_days)
            a.deliberation_duration_days = new_delib_days

        a.deadline_multiplier = current_multiplier
        updated.append({"code": a.code, "status": a.status, "old_multiplier": stored, "new_multiplier": current_multiplier})

    await db.commit()
    return {"multiplier": current_multiplier, "updated": updated}
