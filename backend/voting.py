from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, func, case


from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Amendment, AmendmentVote, VoteHistory, Signature, Reaction
from auth_dependencies import get_current_signer, get_optional_signer
from utils import strip_html

router = APIRouter(tags=["voting"])

VALID_VOTES = {"FOR", "AGAINST", "ABSTAIN"}
VALID_REACTIONS = {"pertinent", "enrichissant", "hors_sujet"}


class VoteRequest(BaseModel):
    vote: str
    comment: str | None = None


class ReactionRequest(BaseModel):
    reaction_type: str


# ── Public endpoints ────────────────────────────


@router.get("/amendments/voting")
async def list_voting_amendments(db: AsyncSession = Depends(get_db)):
    """List amendments currently open for voting."""
    stmt = (
        select(Amendment)
        .where(
            Amendment.status == "deliberation",
            Amendment.vote_opened_at.isnot(None),
        )
        .order_by(Amendment.vote_opened_at.desc())
    )
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
                "status": a.status,
                "vote_threshold": a.vote_threshold,
                "votes_for": a.votes_for,
                "votes_against": a.votes_against,
                "votes_abstain": a.votes_abstain,
                "vote_opened_at": a.vote_opened_at.isoformat() if a.vote_opened_at else None,
                "vote_closed_at": a.vote_closed_at.isoformat() if a.vote_closed_at else None,
            }
            for a in amendments
        ]
    }


@router.get("/amendments/{amendment_id}/votes")
async def get_votes(
    amendment_id: int,
    voter_id: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Public: all votes with motivations for an amendment."""
    stmt = (
        select(
            AmendmentVote.id,
            AmendmentVote.voter_identity,
            AmendmentVote.vote,
            AmendmentVote.comment,
            AmendmentVote.voted_at,
        )
        .where(
            AmendmentVote.amendment_id == amendment_id,
            AmendmentVote.voter_type == "human",
        )
        .order_by(AmendmentVote.voted_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    # Resolve voter names from signatures
    voter_ids = [r.voter_identity for r in rows if r.voter_identity]
    signer_names = {}
    if voter_ids:
        int_ids = [int(vid) for vid in voter_ids if vid and vid.isdigit()]
        if int_ids:
            names_result = await db.execute(
                select(Signature.id, Signature.pseudo).where(Signature.id.in_(int_ids))
            )
            signer_names = {str(r.id): r.pseudo for r in names_result.all()}

    # Check which votes have history (modified)
    vote_ids = [r.id for r in rows]
    modified_ids = set()
    if vote_ids:
        hist_result = await db.execute(
            select(VoteHistory.vote_id).where(VoteHistory.vote_id.in_(vote_ids)).distinct()
        )
        modified_ids = {r.vote_id for r in hist_result.all()}

    votes = []
    for r in rows:
        votes.append({
            "id": r.id,
            "voter_identity": r.voter_identity,
            "voter_name": signer_names.get(r.voter_identity, "Anonyme"),
            "vote": r.vote,
            "comment": r.comment,
            "voted_at": r.voted_at.isoformat() if r.voted_at else None,
            "modified": r.id in modified_ids,
        })

    # If voter_id provided, move their vote to top (match by voter_identity)
    if voter_id:
        vid_str = str(voter_id)
        voter_vote = [v for v in votes if v.get("voter_identity") == vid_str]
        other_votes = [v for v in votes if v.get("voter_identity") != vid_str]
        votes = voter_vote + other_votes

    return {"votes": votes}


@router.get("/amendments/{amendment_id}/votes/{vote_id}/history")
async def get_vote_history(
    amendment_id: int, vote_id: int, db: AsyncSession = Depends(get_db)
):
    """Public: modification history of a specific vote."""
    # Validate vote belongs to amendment
    vote_check = await db.execute(
        select(AmendmentVote.id).where(
            AmendmentVote.id == vote_id,
            AmendmentVote.amendment_id == amendment_id,
        )
    )
    if not vote_check.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Vote not found for this amendment")

    result = await db.execute(
        select(VoteHistory)
        .where(VoteHistory.vote_id == vote_id)
        .order_by(VoteHistory.changed_at.desc())
    )
    history = result.scalars().all()

    return {
        "history": [
            {
                "previous_vote": h.previous_vote,
                "previous_comment": h.previous_comment,
                "changed_at": h.changed_at.isoformat() if h.changed_at else None,
            }
            for h in history
        ]
    }


# ── Reactions on vote motivations ───────────────


@router.get("/amendments/{amendment_id}/votes/{vote_id}/reactions")
async def get_vote_reactions(
    amendment_id: int, vote_id: int, db: AsyncSession = Depends(get_db)
):
    """Public: reaction counts on a vote motivation."""
    stmt = select(
        func.coalesce(func.sum(case((Reaction.reaction_type == "pertinent", 1), else_=0)), 0).label("pertinent"),
        func.coalesce(func.sum(case((Reaction.reaction_type == "enrichissant", 1), else_=0)), 0).label("enrichissant"),
        func.coalesce(func.sum(case((Reaction.reaction_type == "hors_sujet", 1), else_=0)), 0).label("hors_sujet"),
    ).where(Reaction.comment_id == vote_id)

    result = await db.execute(stmt)
    row = result.one()
    return {"pertinent": row.pertinent, "enrichissant": row.enrichissant, "hors_sujet": row.hors_sujet}


@router.post("/amendments/{amendment_id}/votes/{vote_id}/reactions")
async def add_vote_reaction(
    amendment_id: int, vote_id: int,
    body: ReactionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    signer: dict = Depends(get_current_signer),
):
    """Auth required: toggle reaction on a vote motivation."""
    if body.reaction_type not in VALID_REACTIONS:
        raise HTTPException(status_code=400, detail="Invalid reaction_type")

    # Verify vote exists
    vote_result = await db.execute(
        select(AmendmentVote.id).where(
            AmendmentVote.id == vote_id,
            AmendmentVote.amendment_id == amendment_id,
        )
    )
    if not vote_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Vote not found")

    fingerprint = str(signer["sub"])

    # Toggle: if exists, remove; else add
    existing = await db.execute(
        select(Reaction).where(
            Reaction.comment_id == vote_id,
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
        comment_id=vote_id,
        reaction_type=body.reaction_type,
        fingerprint=fingerprint,
    )
    db.add(reaction)
    await db.commit()
    return {"message": "added"}


# ── Authenticated endpoints ─────────────────────


@router.post("/amendments/{amendment_id}/vote")
async def submit_vote(
    amendment_id: int,
    body: VoteRequest,
    db: AsyncSession = Depends(get_db),
    signer: dict = Depends(get_current_signer),
):
    """Submit or modify a vote. Auth required."""
    vote_value = body.vote.upper()
    if vote_value not in VALID_VOTES:
        raise HTTPException(status_code=422, detail=f"Invalid vote. Must be one of: {', '.join(VALID_VOTES)}")

    # Validate and sanitize comment
    comment = strip_html(body.comment.strip()) if body.comment else None
    if comment and len(comment) > 500:
        raise HTTPException(status_code=422, detail="Comment too long (max 500 characters)")

    # Check amendment exists and is in deliberation
    result = await db.execute(select(Amendment).where(Amendment.id == amendment_id))
    amendment = result.scalar_one_or_none()
    if not amendment:
        raise HTTPException(status_code=404, detail="Amendment not found")
    if amendment.status != "deliberation":
        raise HTTPException(status_code=409, detail="Amendment is not in deliberation")

    # Check vote period
    now = datetime.utcnow()
    if amendment.vote_closed_at:
        closed = amendment.vote_closed_at
        if closed.tzinfo is not None:
            closed = closed.replace(tzinfo=None)
        if now >= closed:
            raise HTTPException(status_code=403, detail="Vote period closed")

    voter_identity = str(signer["sub"])

    # Check for existing vote
    existing_result = await db.execute(
        select(AmendmentVote).where(
            AmendmentVote.amendment_id == amendment_id,
            AmendmentVote.voter_identity == voter_identity,
        )
    )
    existing_vote = existing_result.scalar_one_or_none()

    if existing_vote:
        # Rate limit: max 10 modifications per amendment per user per hour
        since = datetime.utcnow() - timedelta(hours=1)
        mod_count = await db.execute(
            select(func.count(VoteHistory.id)).where(
                VoteHistory.vote_id == existing_vote.id,
                VoteHistory.changed_at >= since,
            )
        )
        if mod_count.scalar() >= 10:
            raise HTTPException(status_code=429, detail="Too many vote modifications. Try again later.")

        # Modification — create history entry
        history = VoteHistory(
            vote_id=existing_vote.id,
            previous_vote=existing_vote.vote,
            previous_comment=existing_vote.comment,
        )
        db.add(history)

        # Update counters (decrement old, increment new)
        old_vote = existing_vote.vote.upper()
        _update_counter(amendment, old_vote, -1)
        _update_counter(amendment, vote_value, 1)

        # Update vote
        existing_vote.vote = vote_value
        existing_vote.comment = comment
        existing_vote.voted_at = now

        await db.commit()
        return {"message": "vote_modified"}

    # New vote
    new_vote = AmendmentVote(
        amendment_id=amendment_id,
        voter_type="human",
        voter_identity=voter_identity,
        vote=vote_value,
        comment=comment,
    )
    db.add(new_vote)
    _update_counter(amendment, vote_value, 1)

    await db.commit()
    return {"message": "vote_submitted"}


def _update_counter(amendment: Amendment, vote_value: str, delta: int):
    """Atomic increment/decrement of denormalized vote counters (SQL-level)."""
    if vote_value == "FOR":
        amendment.votes_for = Amendment.votes_for + delta
    elif vote_value == "AGAINST":
        amendment.votes_against = Amendment.votes_against + delta
    elif vote_value == "ABSTAIN":
        amendment.votes_abstain = Amendment.votes_abstain + delta
