import re
import uuid
import math
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Amendment, Signature, DraftShareToken, DraftComment, AmendmentSupport
from auth_dependencies import get_current_signer

router = APIRouter(prefix="/proposals", tags=["proposals"])

# ── Tier configuration ────────────────────────────
TIER_CONFIG = {
    "mineur": {"support_pct": 0.05, "support_floor": 3, "expiry_days": 60, "delib_days": 14},
    "substantiel": {"support_pct": 0.10, "support_floor": 10, "expiry_days": 90, "delib_days": 21},
    "fondateur": {"support_pct": 0.20, "support_floor": 25, "expiry_days": 120, "delib_days": 30},
}

VALID_AMENDMENT_TYPES = {"addition", "modification", "suppression"}
VALID_TIERS = {"mineur", "substantiel", "fondateur"}
VALID_PRINCIPLES = {
    "bienveillance", "transparence", "reciprocite", "souverainete",
    "refus", "proactive", "agentique", "deliberation",
}

CHARTER_PRINCIPLES = [
    {"id": "bienveillance", "label": "Bienveillance"},
    {"id": "transparence", "label": "Transparence"},
    {"id": "reciprocite", "label": "Reciprocite"},
    {"id": "souverainete", "label": "Souverainete"},
    {"id": "refus", "label": "Droit de refus"},
    {"id": "proactive", "label": "Securite proactive"},
    {"id": "agentique", "label": "Agentique"},
    {"id": "deliberation", "label": "Deliberation"},
]


def strip_html(text: str) -> str:
    """Remove HTML tags from user input (defense-in-depth)."""
    return re.sub(r'<[^>]+>', '', text)


# ── Pydantic models ──────────────────────────────

class DraftCreateRequest(BaseModel):
    amendment_type: str
    title: str
    principle_id: str | None = None
    text_after: str
    motivation: str
    tier: str
    submission_language: str = "fr"
    suggested_position: int | None = None
    deletion_justification: str | None = None


class DraftUpdateRequest(BaseModel):
    title: str | None = None
    principle_id: str | None = None
    text_after: str | None = None
    motivation: str | None = None
    tier: str | None = None
    submission_language: str | None = None
    suggested_position: int | None = None
    deletion_justification: str | None = None


class DraftCommentRequest(BaseModel):
    author_name: str
    comment: str


class SupportRequest(BaseModel):
    comment: str | None = None


# ── Helpers ───────────────────────────────────────

async def _generate_code(db: AsyncSession) -> str:
    """Generate next proposal code like P001, P002, etc."""
    result = await db.execute(
        select(func.max(Amendment.code))
        .where(Amendment.code.like("P%"))
    )
    max_code = result.scalar_one_or_none()
    if max_code:
        try:
            num = int(max_code[1:]) + 1
        except (ValueError, IndexError):
            num = 1
    else:
        num = 1
    return f"P{num:03d}"


def _force_tier_for_type(amendment_type: str, tier: str) -> str:
    """Force tier=fondateur for addition/suppression types."""
    if amendment_type in ("addition", "suppression"):
        return "fondateur"
    return tier


# ── Charter principles (public) ───────────────────

@router.get("/charter/principles", tags=["proposals"])
async def charter_principles():
    """Return the 8 charter principles."""
    return {"principles": CHARTER_PRINCIPLES}


# ── Drafts (auth required) ───────────────────────

@router.get("/drafts")
async def list_drafts(
    db: AsyncSession = Depends(get_db),
    signer: dict = Depends(get_current_signer),
):
    """List current user's drafts."""
    result = await db.execute(
        select(Amendment)
        .where(Amendment.status == "draft", Amendment.author_id == signer["sub"])
        .order_by(Amendment.proposed_at.desc())
    )
    drafts = result.scalars().all()

    return {
        "drafts": [
            {
                "id": d.id,
                "code": d.code,
                "title": d.title,
                "amendment_type": d.amendment_type,
                "principle_id": d.principle_id,
                "text_after": d.text_after,
                "motivation": d.motivation,
                "tier": d.tier,
                "status": d.status,
                "submission_language": d.submission_language,
                "suggested_position": d.suggested_position,
                "deletion_justification": d.deletion_justification,
                "proposed_at": d.proposed_at.isoformat() if d.proposed_at else None,
            }
            for d in drafts
        ]
    }


@router.post("/drafts")
async def create_draft(
    body: DraftCreateRequest,
    db: AsyncSession = Depends(get_db),
    signer: dict = Depends(get_current_signer),
):
    """Create a new draft amendment. Max 5 active drafts per user."""
    # Validate amendment_type
    if body.amendment_type not in VALID_AMENDMENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid amendment_type. Must be one of: {', '.join(VALID_AMENDMENT_TYPES)}")

    # Validate tier
    if body.tier not in VALID_TIERS:
        raise HTTPException(status_code=400, detail=f"Invalid tier. Must be one of: {', '.join(VALID_TIERS)}")

    # Validate principle_id (required for modification/suppression)
    if body.amendment_type in ("modification", "suppression"):
        if not body.principle_id or body.principle_id not in VALID_PRINCIPLES:
            raise HTTPException(status_code=400, detail="Valid principle_id required for modification/suppression")

    if body.principle_id and body.principle_id not in VALID_PRINCIPLES:
        raise HTTPException(status_code=400, detail="Invalid principle_id")

    # Sanitize inputs
    title = strip_html(body.title.strip())
    text_after = strip_html(body.text_after.strip())
    motivation = strip_html(body.motivation.strip())

    if not title or not text_after or not motivation:
        raise HTTPException(status_code=400, detail="title, text_after, and motivation are required")

    if len(title) > 120:
        raise HTTPException(status_code=400, detail="Title too long (max 120)")

    # Check max 5 active drafts
    count_result = await db.execute(
        select(func.count(Amendment.id))
        .where(Amendment.status == "draft", Amendment.author_id == signer["sub"])
    )
    if count_result.scalar() >= 5:
        raise HTTPException(status_code=409, detail="Maximum 5 active drafts reached")

    # Force tier for addition/suppression
    tier = _force_tier_for_type(body.amendment_type, body.tier)

    # Generate code
    code = await _generate_code(db)

    # Determine target
    if body.amendment_type == "addition":
        target = "principle_body"
    elif body.amendment_type == "suppression":
        target = "principle_body"
    else:
        target = "principle_body"

    draft = Amendment(
        code=code,
        title=title,
        principle_id=body.principle_id,
        target=target,
        amendment_type=body.amendment_type,
        text_after=text_after,
        motivation=motivation,
        tier=tier,
        status="draft",
        source_type="community",
        phase="phase_2",
        author_id=signer["sub"],
        submission_language=body.submission_language or "fr",
        suggested_position=body.suggested_position,
        deletion_justification=strip_html(body.deletion_justification.strip()) if body.deletion_justification else None,
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)

    return {
        "id": draft.id,
        "code": draft.code,
        "title": draft.title,
        "status": draft.status,
        "tier": draft.tier,
    }


@router.put("/drafts/{draft_id}")
async def update_draft(
    draft_id: int,
    body: DraftUpdateRequest,
    db: AsyncSession = Depends(get_db),
    signer: dict = Depends(get_current_signer),
):
    """Update a draft. Only author, only while status=draft."""
    result = await db.execute(select(Amendment).where(Amendment.id == draft_id))
    draft = result.scalar_one_or_none()

    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft.author_id != signer["sub"]:
        raise HTTPException(status_code=403, detail="Not your draft")
    if draft.status != "draft":
        raise HTTPException(status_code=409, detail="Can only edit drafts")

    if body.title is not None:
        draft.title = strip_html(body.title.strip())
    if body.principle_id is not None:
        if body.principle_id not in VALID_PRINCIPLES:
            raise HTTPException(status_code=400, detail="Invalid principle_id")
        draft.principle_id = body.principle_id
    if body.text_after is not None:
        draft.text_after = strip_html(body.text_after.strip())
    if body.motivation is not None:
        draft.motivation = strip_html(body.motivation.strip())
    if body.tier is not None:
        if body.tier not in VALID_TIERS:
            raise HTTPException(status_code=400, detail="Invalid tier")
        draft.tier = _force_tier_for_type(draft.amendment_type, body.tier)
    if body.submission_language is not None:
        draft.submission_language = body.submission_language
    if body.suggested_position is not None:
        draft.suggested_position = body.suggested_position
    if body.deletion_justification is not None:
        draft.deletion_justification = strip_html(body.deletion_justification.strip())

    await db.commit()
    return {"message": "updated"}


@router.delete("/drafts/{draft_id}")
async def delete_draft(
    draft_id: int,
    db: AsyncSession = Depends(get_db),
    signer: dict = Depends(get_current_signer),
):
    """Delete a draft. Only author, only while status=draft."""
    result = await db.execute(select(Amendment).where(Amendment.id == draft_id))
    draft = result.scalar_one_or_none()

    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft.author_id != signer["sub"]:
        raise HTTPException(status_code=403, detail="Not your draft")
    if draft.status != "draft":
        raise HTTPException(status_code=409, detail="Can only delete drafts")

    await db.delete(draft)
    await db.commit()
    return {"message": "deleted"}


@router.post("/drafts/{draft_id}/submit")
async def submit_draft(
    draft_id: int,
    db: AsyncSession = Depends(get_db),
    signer: dict = Depends(get_current_signer),
):
    """Submit a draft: transitions from draft to proposed."""
    result = await db.execute(select(Amendment).where(Amendment.id == draft_id))
    draft = result.scalar_one_or_none()

    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft.author_id != signer["sub"]:
        raise HTTPException(status_code=403, detail="Not your draft")
    if draft.status != "draft":
        raise HTTPException(status_code=409, detail="Can only submit drafts")

    # Force tier for addition/suppression
    draft.tier = _force_tier_for_type(draft.amendment_type, draft.tier)

    tier_cfg = TIER_CONFIG[draft.tier]
    now = datetime.utcnow()

    draft.status = "proposed"
    draft.proposed_at = now
    draft.expires_at = now + timedelta(days=tier_cfg["expiry_days"])
    draft.deliberation_duration_days = tier_cfg["delib_days"]

    await db.commit()

    return {
        "message": "submitted",
        "status": draft.status,
        "expires_at": draft.expires_at.isoformat(),
        "deliberation_duration_days": draft.deliberation_duration_days,
    }


@router.post("/drafts/{draft_id}/share")
async def share_draft(
    draft_id: int,
    db: AsyncSession = Depends(get_db),
    signer: dict = Depends(get_current_signer),
):
    """Generate a share token for a draft."""
    result = await db.execute(select(Amendment).where(Amendment.id == draft_id))
    draft = result.scalar_one_or_none()

    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft.author_id != signer["sub"]:
        raise HTTPException(status_code=403, detail="Not your draft")
    if draft.status != "draft":
        raise HTTPException(status_code=409, detail="Can only share drafts")

    token = uuid.uuid4().hex
    share = DraftShareToken(
        amendment_id=draft_id,
        token=token,
    )
    db.add(share)
    await db.commit()

    return {"token": token}


# ── Shared drafts (no auth) ──────────────────────

@router.get("/shared/{token}")
async def read_shared_draft(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Read a shared draft via token. No auth required."""
    result = await db.execute(
        select(DraftShareToken).where(DraftShareToken.token == token)
    )
    share = result.scalar_one_or_none()
    if not share:
        raise HTTPException(status_code=404, detail="Share link not found")

    result = await db.execute(
        select(Amendment).where(Amendment.id == share.amendment_id)
    )
    draft = result.scalar_one_or_none()
    if not draft or draft.status != "draft":
        raise HTTPException(status_code=404, detail="Draft no longer available")

    # Load comments
    comments_result = await db.execute(
        select(DraftComment)
        .where(DraftComment.amendment_id == draft.id)
        .order_by(DraftComment.created_at.desc())
    )
    comments = comments_result.scalars().all()

    return {
        "draft": {
            "id": draft.id,
            "code": draft.code,
            "title": draft.title,
            "amendment_type": draft.amendment_type,
            "principle_id": draft.principle_id,
            "text_after": draft.text_after,
            "motivation": draft.motivation,
            "tier": draft.tier,
            "submission_language": draft.submission_language,
        },
        "comments": [
            {
                "id": c.id,
                "author_name": c.author_name,
                "comment": c.comment,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in comments
        ],
    }


@router.post("/shared/{token}/comments")
async def add_shared_comment(
    token: str,
    body: DraftCommentRequest,
    db: AsyncSession = Depends(get_db),
):
    """Add a comment to a shared draft. No auth required."""
    result = await db.execute(
        select(DraftShareToken).where(DraftShareToken.token == token)
    )
    share = result.scalar_one_or_none()
    if not share:
        raise HTTPException(status_code=404, detail="Share link not found")

    result = await db.execute(
        select(Amendment).where(Amendment.id == share.amendment_id)
    )
    draft = result.scalar_one_or_none()
    if not draft or draft.status != "draft":
        raise HTTPException(status_code=404, detail="Draft no longer available")

    author_name = strip_html(body.author_name.strip())
    comment_text = strip_html(body.comment.strip())

    if not author_name or not comment_text:
        raise HTTPException(status_code=400, detail="author_name and comment required")
    if len(comment_text) > 500:
        raise HTTPException(status_code=400, detail="Comment too long (max 500)")
    if len(author_name) > 100:
        raise HTTPException(status_code=400, detail="Name too long (max 100)")

    comment = DraftComment(
        amendment_id=draft.id,
        author_name=author_name,
        comment=comment_text,
    )
    db.add(comment)
    await db.commit()

    return {"message": "comment_added"}


# ── Public endpoints ─────────────────────────────

@router.get("/public")
async def list_public_amendments(
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List all non-draft amendments."""
    NON_DRAFT_STATUSES = {"proposed", "deliberation", "accepted", "ratified", "rejected", "withdrawn"}

    stmt = select(Amendment).where(Amendment.status != "draft")

    if status:
        if status not in NON_DRAFT_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status filter")
        stmt = stmt.where(Amendment.status == status)

    stmt = stmt.order_by(Amendment.proposed_at.desc())

    result = await db.execute(stmt)
    amendments = result.scalars().all()

    return {
        "amendments": [
            {
                "id": a.id,
                "code": a.code,
                "title": a.title,
                "principle_id": a.principle_id,
                "target": a.target,
                "amendment_type": a.amendment_type,
                "text_before": a.text_before,
                "text_after": a.text_after,
                "motivation": a.motivation,
                "tier": a.tier,
                "status": a.status,
                "author_id": a.author_id,
                "votes_for": a.votes_for,
                "votes_against": a.votes_against,
                "votes_abstain": a.votes_abstain,
                "proposed_at": a.proposed_at.isoformat() if a.proposed_at else None,
                "expires_at": a.expires_at.isoformat() if a.expires_at else None,
                "vote_opened_at": a.vote_opened_at.isoformat() if a.vote_opened_at else None,
                "vote_closed_at": a.vote_closed_at.isoformat() if a.vote_closed_at else None,
                "tier_requalified": a.tier_requalified,
                "withdrawn_at": a.withdrawn_at.isoformat() if a.withdrawn_at else None,
            }
            for a in amendments
        ]
    }


@router.get("/{amendment_id}/supports")
async def list_supports(
    amendment_id: int,
    db: AsyncSession = Depends(get_db),
):
    """List supports for an amendment (public)."""
    result = await db.execute(
        select(AmendmentSupport)
        .where(AmendmentSupport.amendment_id == amendment_id)
        .order_by(AmendmentSupport.created_at.desc())
    )
    supports = result.scalars().all()

    # Resolve signer names
    signer_ids = [s.signer_id for s in supports]
    signer_names = {}
    if signer_ids:
        names_result = await db.execute(
            select(Signature.id, Signature.pseudo).where(Signature.id.in_(signer_ids))
        )
        signer_names = {r.id: r.pseudo for r in names_result.all()}

    return {
        "supports": [
            {
                "id": s.id,
                "signer_id": s.signer_id,
                "signer_name": signer_names.get(s.signer_id, "Anonyme"),
                "comment": s.comment,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in supports
        ]
    }


# ── Auth required ─────────────────────────────────

@router.post("/{amendment_id}/support")
async def support_proposal(
    amendment_id: int,
    body: SupportRequest,
    db: AsyncSession = Depends(get_db),
    signer: dict = Depends(get_current_signer),
):
    """Support a proposal. Auth required."""
    result = await db.execute(select(Amendment).where(Amendment.id == amendment_id))
    amendment = result.scalar_one_or_none()

    if not amendment:
        raise HTTPException(status_code=404, detail="Amendment not found")
    if amendment.status != "proposed":
        raise HTTPException(status_code=409, detail="Can only support proposed amendments")
    if amendment.author_id == signer["sub"]:
        raise HTTPException(status_code=409, detail="Cannot support your own proposal")

    # Check not already supported
    existing = await db.execute(
        select(AmendmentSupport).where(
            AmendmentSupport.amendment_id == amendment_id,
            AmendmentSupport.signer_id == signer["sub"],
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Already supported")

    comment = strip_html(body.comment.strip()) if body.comment else None

    support = AmendmentSupport(
        amendment_id=amendment_id,
        signer_id=signer["sub"],
        comment=comment,
    )
    db.add(support)
    await db.commit()

    # Check if support threshold reached
    support_count_result = await db.execute(
        select(func.count(AmendmentSupport.id))
        .where(AmendmentSupport.amendment_id == amendment_id)
    )
    support_count = support_count_result.scalar()

    # Get total confirmed signers
    total_result = await db.execute(
        select(func.count(Signature.id)).where(Signature.confirmed == True)
    )
    total_confirmed = total_result.scalar() or 0

    tier_cfg = TIER_CONFIG[amendment.tier]
    threshold = max(tier_cfg["support_floor"], math.ceil(tier_cfg["support_pct"] * total_confirmed))

    if support_count >= threshold:
        # Auto-transition to deliberation
        now = datetime.utcnow()
        amendment.status = "deliberation"
        amendment.vote_opened_at = now
        amendment.vote_closed_at = now + timedelta(days=amendment.deliberation_duration_days or tier_cfg["delib_days"])
        await db.commit()
        return {"message": "supported", "threshold_reached": True, "new_status": "deliberation"}

    return {"message": "supported", "threshold_reached": False, "supports": support_count, "threshold": threshold}


@router.post("/{amendment_id}/withdraw")
async def withdraw_proposal(
    amendment_id: int,
    db: AsyncSession = Depends(get_db),
    signer: dict = Depends(get_current_signer),
):
    """Withdraw a proposal. Author only, status must be proposed."""
    result = await db.execute(select(Amendment).where(Amendment.id == amendment_id))
    amendment = result.scalar_one_or_none()

    if not amendment:
        raise HTTPException(status_code=404, detail="Amendment not found")
    if amendment.author_id != signer["sub"]:
        raise HTTPException(status_code=403, detail="Not your proposal")
    if amendment.status != "proposed":
        raise HTTPException(status_code=409, detail="Can only withdraw proposed amendments")

    amendment.status = "withdrawn"
    amendment.withdrawn_at = datetime.utcnow()
    await db.commit()

    return {"message": "withdrawn"}
