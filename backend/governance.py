import os
import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Amendment, TierChallenge, ContentReport, AdminAction, Signature
from auth_dependencies import get_current_signer

router = APIRouter(tags=["governance"])

# ── Admin auth ────────────────────────────────────
ADMIN_KEY = os.getenv("ADMIN_KEY", "")


def verify_admin(x_admin_key: str = Header(None)):
    if not x_admin_key or not ADMIN_KEY or not hmac.compare_digest(x_admin_key, ADMIN_KEY):
        raise HTTPException(status_code=403, detail="Forbidden")


# ── Tier ordering ─────────────────────────────────
TIER_ORDER = {"mineur": 0, "substantiel": 1, "fondateur": 2}


# ── Pydantic schemas ─────────────────────────────
class ChallengeTierRequest(BaseModel):
    suggested_tier: str


class ReportRequest(BaseModel):
    category: str


class AdminDeleteRequest(BaseModel):
    reason: str
    via: str


class AdminDismissReportsRequest(BaseModel):
    reason: str


class AdminRequalifyRequest(BaseModel):
    new_tier: str
    reason: str


# ── Tier challenges ──────────────────────────────

@router.post("/proposals/{id}/challenge-tier")
async def challenge_tier(
    id: int,
    body: ChallengeTierRequest,
    signer: dict = Depends(get_current_signer),
    db: AsyncSession = Depends(get_db),
):
    # Validate suggested_tier
    if body.suggested_tier not in TIER_ORDER:
        raise HTTPException(status_code=422, detail="Invalid tier value")

    # Fetch amendment
    result = await db.execute(select(Amendment).where(Amendment.id == id))
    amendment = result.scalar_one_or_none()
    if not amendment:
        raise HTTPException(status_code=404, detail="Amendment not found")

    # Can't challenge addition/suppression (already fondateur-level)
    if amendment.amendment_type in ("addition", "suppression"):
        raise HTTPException(status_code=422, detail="Cannot challenge tier for addition/suppression amendments")

    current_tier = amendment.tier or "mineur"

    # Suggested tier must be strictly higher than current tier
    if TIER_ORDER.get(body.suggested_tier, 0) <= TIER_ORDER.get(current_tier, 0):
        raise HTTPException(status_code=422, detail="Suggested tier must be higher than current tier")

    # Unique per challenger
    challenger_id = signer["sub"]
    existing = await db.execute(
        select(TierChallenge).where(
            TierChallenge.amendment_id == id,
            TierChallenge.challenger_id == challenger_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Already challenged")

    challenge = TierChallenge(
        amendment_id=id,
        challenger_id=challenger_id,
        suggested_tier=body.suggested_tier,
    )
    db.add(challenge)
    await db.flush()

    # Check if 3 challenges reached
    count_result = await db.execute(
        select(func.count()).select_from(TierChallenge).where(TierChallenge.amendment_id == id)
    )
    challenge_count = count_result.scalar()

    if challenge_count >= 3:
        # Get all suggested tiers
        tiers_result = await db.execute(
            select(TierChallenge.suggested_tier).where(TierChallenge.amendment_id == id)
        )
        tiers = [row[0] for row in tiers_result.all()]
        unique_tiers = set(tiers)

        if len(unique_tiers) == 1:
            # All agree → auto-requalify
            new_tier = unique_tiers.pop()
            amendment.tier_original = current_tier
            amendment.tier = new_tier
            amendment.tier_requalified = True
            amendment.tier_requalified_by = "auto"
            amendment.tier_requalified_at = datetime.utcnow()

            action = AdminAction(
                amendment_id=id,
                action="tier_requalified",
                reason=f"Auto-requalified from {current_tier} to {new_tier} (3 convergent challenges)",
                via="auto",
            )
            db.add(action)
        else:
            # Divergent → log but don't auto-requalify
            action = AdminAction(
                amendment_id=id,
                action="tier_challenge_divergent",
                reason=f"3 challenges received with divergent suggestions: {', '.join(tiers)}",
                via="auto",
            )
            db.add(action)

    await db.commit()
    return {"message": "Challenge recorded"}


@router.get("/proposals/{id}/challenges")
async def list_challenges(
    id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TierChallenge).where(TierChallenge.amendment_id == id).order_by(TierChallenge.created_at)
    )
    challenges = result.scalars().all()
    return {
        "challenges": [
            {
                "id": c.id,
                "amendment_id": c.amendment_id,
                "challenger_id": c.challenger_id,
                "suggested_tier": c.suggested_tier,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in challenges
        ]
    }


# ── Content reports ──────────────────────────────

VALID_REPORT_CATEGORIES = {"spam", "hors_charte", "contenu_inapproprie"}


@router.post("/proposals/{id}/report")
async def report_proposal(
    id: int,
    body: ReportRequest,
    signer: dict = Depends(get_current_signer),
    db: AsyncSession = Depends(get_db),
):
    if body.category not in VALID_REPORT_CATEGORIES:
        raise HTTPException(status_code=422, detail="Invalid category")

    # Fetch amendment
    result = await db.execute(select(Amendment).where(Amendment.id == id))
    amendment = result.scalar_one_or_none()
    if not amendment:
        raise HTTPException(status_code=404, detail="Amendment not found")

    reporter_id = signer["sub"]

    # Unique per reporter
    existing = await db.execute(
        select(ContentReport).where(
            ContentReport.amendment_id == id,
            ContentReport.reporter_id == reporter_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Already reported")

    report = ContentReport(
        amendment_id=id,
        reporter_id=reporter_id,
        category=body.category,
    )
    db.add(report)
    await db.commit()

    return {"message": "Report recorded"}


# ── Admin actions ────────────────────────────────

@router.post("/admin/amendments/{id}/delete")
async def admin_delete_amendment(
    id: int,
    body: AdminDeleteRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
):
    result = await db.execute(select(Amendment).where(Amendment.id == id))
    amendment = result.scalar_one_or_none()
    if not amendment:
        raise HTTPException(status_code=404, detail="Amendment not found")

    amendment.status = "deleted"

    action = AdminAction(
        amendment_id=id,
        action="deleted",
        reason=body.reason,
        via=body.via,
    )
    db.add(action)
    await db.commit()

    return {"message": "Amendment deleted"}


@router.post("/admin/amendments/{id}/dismiss-reports")
async def admin_dismiss_reports(
    id: int,
    body: AdminDismissReportsRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
):
    result = await db.execute(select(Amendment).where(Amendment.id == id))
    amendment = result.scalar_one_or_none()
    if not amendment:
        raise HTTPException(status_code=404, detail="Amendment not found")

    action = AdminAction(
        amendment_id=id,
        action="reports_dismissed",
        reason=body.reason,
        via="direct_action",
    )
    db.add(action)
    await db.commit()

    return {"message": "Reports dismissed"}


@router.post("/admin/amendments/{id}/requalify-tier")
async def admin_requalify_tier(
    id: int,
    body: AdminRequalifyRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
):
    if body.new_tier not in TIER_ORDER:
        raise HTTPException(status_code=422, detail="Invalid tier value")

    result = await db.execute(select(Amendment).where(Amendment.id == id))
    amendment = result.scalar_one_or_none()
    if not amendment:
        raise HTTPException(status_code=404, detail="Amendment not found")

    current_tier = amendment.tier or "mineur"
    amendment.tier_original = current_tier
    amendment.tier = body.new_tier
    amendment.tier_requalified = True
    amendment.tier_requalified_by = "admin"
    amendment.tier_requalified_at = datetime.utcnow()

    action = AdminAction(
        amendment_id=id,
        action="tier_requalified",
        reason=body.reason,
        via="direct_action",
    )
    db.add(action)
    await db.commit()

    return {"message": "Tier requalified"}


# ── Transparency ─────────────────────────────────

@router.get("/transparency/actions")
async def transparency_actions(
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AdminAction).order_by(AdminAction.acted_at.desc())
    )
    actions = result.scalars().all()
    return {
        "actions": [
            {
                "id": a.id,
                "amendment_id": a.amendment_id,
                "action": a.action,
                "reason": a.reason,
                "via": a.via,
                "acted_at": a.acted_at.isoformat() if a.acted_at else None,
            }
            for a in actions
        ]
    }


@router.get("/transparency/changelog")
async def transparency_changelog():
    """Serve the CHANGELOG.md content parsed into entries."""
    import os
    changelog_path = os.path.join(os.path.dirname(__file__), "..", "CHANGELOG.md")
    try:
        with open(changelog_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return {"entries": []}

    entries = []
    current = None
    for line in content.split("\n"):
        if line.startswith("## ["):
            if current:
                entries.append(current)
            bracket_end = line.index("]")
            date = line[4:bracket_end]
            title = line[bracket_end + 1:].strip().lstrip("—").lstrip("-").strip()
            current = {"date": date, "title": title, "items": []}
        elif line.startswith("- ") and current:
            current["items"].append(line[2:].strip())

    if current:
        entries.append(current)

    return {"entries": entries}
