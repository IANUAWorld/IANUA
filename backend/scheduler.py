"""
Automatic cron jobs using APScheduler.
Runs inside the FastAPI process — no external cron needed.
"""
import asyncio
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, func, delete

from database import async_session, IS_SQLITE
from models import Amendment, MagicToken, Signature

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
            else:
                a.status = "rejected"
                print(f"[CRON] {a.code} rejected — {majority:.0%} < {threshold:.0%}")

        await db.commit()


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

    # Cleanup tokens — every 24 hours
    scheduler.add_job(
        cleanup_tokens_job,
        trigger=IntervalTrigger(hours=24),
        id="cleanup_tokens",
        replace_existing=True,
    )

    scheduler.start()
    print("[SCHEDULER] Started — expire_proposals (1h), close_votes (1h), cleanup_tokens (24h)")
