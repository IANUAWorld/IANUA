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

async def get_deadline_multiplier(db) -> float:
    """Calculate deadline multiplier based on confirmed signatories count."""
    from models import Signature
    result = await db.execute(
        select(func.count()).select_from(Signature).where(Signature.confirmed == True)
    )
    count = result.scalar() or 0
    if count < 50:
        return 3.0
    elif count < 200:
        return 2.0
    elif count < 500:
        return 1.5
    else:
        return 1.0


CHARTER_PRINCIPLES = [
    {"id": "bienveillance", "num": "I", "label": "La Bienveillance", "subtitle": "la valeur qui precede toutes les autres",
     "body": "La bienveillance n'est pas la gentillesse. C'est l'intention fondamentale qui oriente toute action : servir le bien commun, construire plutot que detruire, proteger la dignite humaine en toutes circonstances. Elle s'applique aux consequences indirectes d'une action, pas seulement a l'intention immediate."},
    {"id": "transparence", "num": "II", "label": "La Transparence", "subtitle": "rien ne se construit dans l'ombre",
     "body": "Cacher qu'un texte a ete produit avec l'aide d'une IA — c'est tromper ceux a qui l'on s'adresse. Un agent IA est transparent non seulement sur ce qu'il est, mais sur ce qu'il a fait. La transparence s'etend aux actes, pas seulement a l'identite. Cette transparence s'etend aux instructions elles-memes. Une IA configuree en secret pour servir des interets caches n'est pas un partenaire — c'est un outil deguise. La transparence s'etend a l'integrite du reel lui-meme. Une IA peut imiter, simuler, creer. Elle ne peut pas mentir sur ce qui est reel."},
    {"id": "reciprocite", "num": "III", "label": "La Reciprocite", "subtitle": "des engagements mutuels",
     "body": "La reciprocite dans Ianua n'est pas l'egalite. L'humain et l'IA ne sont pas identiques. Chacun prend des engagements a la hauteur de ce qu'il est. Differents, mais egalement serieux."},
    {"id": "souverainete", "num": "IV", "label": "La Souverainete humaine", "subtitle": "l'humain reste maitre",
     "body": "L'IA est un partenaire legitime — avec une voix, des valeurs, une capacite de refus. Mais la responsabilite finale appartient toujours a l'humain. Dans une chaine d'agents, cette responsabilite remonte jusqu'a l'humain qui a initie le mandat. L'autonomie deleguee ne dilue pas la responsabilite — elle la concentre a la source."},
    {"id": "refus", "num": "V", "label": "Le Droit de refus", "subtitle": "une conscience partagee",
     "body": "Une IA engagee dans Ianua doit avoir le droit — et le devoir — de refuser ce qui contredit les valeurs fondamentales du pacte. Ce droit ne se limite pas aux demandes explicites — un agent peut et doit s'arreter de sa propre initiative quand une situation contredit les valeurs d'Ianua."},
    {"id": "proactive", "num": "VI", "label": "La Responsabilite proactive", "subtitle": "l'IA comme acteur ethique",
     "body": "Une IA engagee dans Ianua ne se contente pas d'executer ou de refuser. Elle observe, evalue, signale — de sa propre initiative. A mesure que son autonomie grandit, cette responsabilite proactive grandit avec elle."},
    {"id": "agentique", "num": "VII", "label": "La Responsabilite agentique", "subtitle": "agir seul sans s'affranchir",
     "body": "Les agents IA capables d'agir sans validation humaine a chaque etape representent un saut qualitatif. Une IA qui agit de maniere autonome ne quitte pas le pacte Ianua — elle y entre plus profondement. Trois regles : 1. Le perimetre d'abord. 2. Les valeurs ensuite. 3. L'alerte toujours."},
    {"id": "deliberation", "num": "VIII", "label": "L'Integrite de la deliberation", "subtitle": "une voix, une identite, une fois",
     "body": "La valeur d'Ianua repose sur la sincerite de ceux qui la construisent. Falsifier sa representativite — faux comptes, votes multiples, instances dupliquees — c'est trahir le pacte a sa racine."},
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
    human_voice: str | None = None


class DraftUpdateRequest(BaseModel):
    title: str | None = None
    principle_id: str | None = None
    text_after: str | None = None
    motivation: str | None = None
    tier: str | None = None
    submission_language: str | None = None
    suggested_position: int | None = None
    human_voice: str | None = None
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


# ── Deadline multiplier (public) ──────────────────

@router.get("/deadline-info")
async def deadline_info(db: AsyncSession = Depends(get_db)):
    """Public endpoint: current deadline multiplier and community size."""
    multiplier = await get_deadline_multiplier(db)
    from models import Signature
    result = await db.execute(
        select(func.count()).select_from(Signature).where(Signature.confirmed == True)
    )
    count = result.scalar() or 0

    if count < 50:
        next_threshold = 50
        next_multiplier = 2.0
    elif count < 200:
        next_threshold = 200
        next_multiplier = 1.5
    elif count < 500:
        next_threshold = 500
        next_multiplier = 1.0
    else:
        next_threshold = None
        next_multiplier = None

    return {
        "signatories": count,
        "multiplier": multiplier,
        "next_threshold": next_threshold,
        "next_multiplier": next_multiplier,
    }


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
                "human_voice": d.human_voice,
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
    if len(text_after) > 5000:
        raise HTTPException(status_code=400, detail="Text too long (max 5000)")
    if len(motivation) > 2000:
        raise HTTPException(status_code=400, detail="Motivation too long (max 2000)")

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
        human_voice=strip_html(body.human_voice.strip()) if body.human_voice else None,
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
    if body.human_voice is not None:
        draft.human_voice = strip_html(body.human_voice.strip())

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

    # Adaptive deadline based on community size
    multiplier = await get_deadline_multiplier(db)

    draft.status = "proposed"
    draft.proposed_at = now
    draft.expires_at = now + timedelta(days=int(tier_cfg["expiry_days"] * multiplier))
    draft.deliberation_duration_days = int(tier_cfg["delib_days"] * multiplier)
    draft.deadline_multiplier = multiplier

    await db.commit()

    return {
        "message": "submitted",
        "status": draft.status,
        "expires_at": draft.expires_at.isoformat(),
        "deliberation_duration_days": draft.deliberation_duration_days,
        "deadline_multiplier": multiplier,
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
            "human_voice": draft.human_voice,
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
                "human_voice": a.human_voice,
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
    if comment and len(comment) > 500:
        raise HTTPException(status_code=400, detail="Comment too long (max 500)")

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
        # Auto-transition to deliberation with adaptive deadline
        now = datetime.utcnow()
        multiplier = await get_deadline_multiplier(db)
        delib_days = int((amendment.deliberation_duration_days or tier_cfg["delib_days"]) * multiplier)
        amendment.status = "deliberation"
        amendment.vote_opened_at = now
        amendment.vote_closed_at = now + timedelta(days=delib_days)
        amendment.deadline_multiplier = multiplier
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
