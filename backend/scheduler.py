"""
Automatic cron jobs using APScheduler.
Runs inside the FastAPI process — no external cron needed.
"""
import asyncio
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, func, delete

from database import async_session, IS_SQLITE
from models import Amendment, MagicToken, Signature, AuditResponse

scheduler = AsyncIOScheduler()

TIER_THRESHOLDS = {
    "mineur": 0.50,
    "substantiel": 2 / 3,
    "fondateur": 2 / 3,
}


async def expire_proposals_job():
    """Expire proposals past their deadline."""
    async with async_session() as db:
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
        if amendments:
            print(f"[CRON] Expired {len(amendments)} proposals")


async def close_votes_job():
    """Close votes and compute ratification results."""
    async with async_session() as db:
        now = datetime.utcnow()
        result = await db.execute(
            select(Amendment).where(
                Amendment.status == "deliberation",
                Amendment.vote_closed_at <= now,
            )
        )
        amendments = result.scalars().all()
        if not amendments:
            return

        sig_count_result = await db.execute(
            select(func.count()).select_from(Signature).where(Signature.confirmed == True)
        )
        confirmed_signatories = sig_count_result.scalar()

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
                    print(f"[CRON] {a.code} rejected — quorum not met")
                    continue

            # Calculate majority: FOR / (FOR + AGAINST)
            decisive_votes = votes_for + votes_against
            if decisive_votes == 0:
                a.status = "rejected"
                print(f"[CRON] {a.code} rejected — no decisive votes")
                continue

            majority = votes_for / decisive_votes
            if majority >= threshold:
                a.status = "ratified"
                a.ratified_at = now
                print(f"[CRON] {a.code} ratified — {majority:.0%}")
                # Trigger automatic IA voice audit
                if a.human_voice:
                    await _trigger_voice_audit_scheduler(db, a)
            else:
                a.status = "rejected"
                print(f"[CRON] {a.code} rejected — {majority:.0%} < {threshold:.0%}")

        await db.commit()


async def _trigger_voice_audit_scheduler(db, amendment):
    """Trigger voice audit from scheduler context."""
    try:
        from crons import _trigger_voice_audit
        await _trigger_voice_audit(db, amendment)
    except Exception as exc:
        print(f"[SCHEDULER] Voice audit failed for {amendment.code}: {exc}")


async def recalculate_deadlines_job():
    """Retroactively adjust deadlines when community size crosses a threshold."""
    async with async_session() as db:
        from proposals import get_deadline_multiplier, TIER_CONFIG

        current_multiplier = await get_deadline_multiplier(db)

        # Find active amendments whose multiplier differs from current
        result = await db.execute(
            select(Amendment).where(
                Amendment.status.in_(["proposed", "deliberation"]),
            )
        )
        amendments = result.scalars().all()

        updated = 0
        for a in amendments:
            stored = a.deadline_multiplier or 1.0
            if abs(stored - current_multiplier) < 0.01:
                continue  # No change needed

            tier_cfg = TIER_CONFIG.get(a.tier or "mineur", TIER_CONFIG["mineur"])

            if a.status == "proposed" and a.proposed_at:
                # Recalculate expires_at from original proposed_at
                new_expiry_days = int(tier_cfg["expiry_days"] * current_multiplier)
                a.expires_at = a.proposed_at + timedelta(days=new_expiry_days)
                a.deliberation_duration_days = int(tier_cfg["delib_days"] * current_multiplier)

            elif a.status == "deliberation" and a.vote_opened_at:
                # Recalculate vote_closed_at from original vote_opened_at
                new_delib_days = int(tier_cfg["delib_days"] * current_multiplier)
                a.vote_closed_at = a.vote_opened_at + timedelta(days=new_delib_days)
                a.deliberation_duration_days = new_delib_days

            a.deadline_multiplier = current_multiplier
            updated += 1

        if updated > 0:
            await db.commit()
            print(f"[CRON] Recalculated deadlines for {updated} amendments (multiplier: x{current_multiplier})")


async def cleanup_tokens_job():
    """Delete used and expired magic tokens."""
    async with async_session() as db:
        now = datetime.utcnow()
        result = await db.execute(
            delete(MagicToken).where(
                (MagicToken.used == True) | (MagicToken.expires_at < now)
            )
        )
        await db.commit()
        if result.rowcount > 0:
            print(f"[CRON] Cleaned up {result.rowcount} magic tokens")


def start_scheduler():
    """Start the APScheduler with all cron jobs."""
    if IS_SQLITE:
        print("[SCHEDULER] Skipping scheduler in dev/SQLite mode")
        return

    # Expire proposals — every hour
    scheduler.add_job(
        expire_proposals_job,
        trigger=IntervalTrigger(hours=1),
        id="expire_proposals",
        replace_existing=True,
    )

    # Close votes — every hour
    scheduler.add_job(
        close_votes_job,
        trigger=IntervalTrigger(hours=1),
        id="close_votes",
        replace_existing=True,
    )

    # Recalculate deadlines — every 6 hours
    scheduler.add_job(
        recalculate_deadlines_job,
        trigger=IntervalTrigger(hours=6),
        id="recalculate_deadlines",
        replace_existing=True,
    )

    # Cleanup tokens — every 24 hours
    scheduler.add_job(
        cleanup_tokens_job,
        trigger=IntervalTrigger(hours=24),
        id="cleanup_tokens",
        replace_existing=True,
    )

    scheduler.start()
    print("[SCHEDULER] Started — expire_proposals (1h), close_votes (1h), recalculate_deadlines (6h), cleanup_tokens (24h)")
