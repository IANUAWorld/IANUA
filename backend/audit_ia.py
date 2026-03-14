"""
IANUA — AI Audit Router
Trigger AI audits on amendments, publish/reject responses, view results.
"""

import os
import hmac

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Amendment, AuditResponse, AdminAction

router = APIRouter(tags=["audit_ia"])

# ── Admin auth (local — avoid circular imports) ──────────────────────

ADMIN_KEY = os.getenv("ADMIN_KEY", "")


def verify_admin(x_admin_key: str = Header(None)):
    if not x_admin_key or not ADMIN_KEY or not hmac.compare_digest(x_admin_key, ADMIN_KEY):
        raise HTTPException(status_code=403, detail="Forbidden")


# ── Provider registry ────────────────────────────────────────────────

AI_PROVIDERS: dict[str, object] = {}  # name -> async callable(prompt) -> (text, version)


async def call_anthropic(prompt: str) -> tuple[str, str]:
    """Call Claude API. Returns (response_text, model_version)."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6-20250514",
                "max_tokens": 2000,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        data = resp.json()
        return data["content"][0]["text"], data.get("model", "claude-sonnet-4-6")


async def call_openai(prompt: str) -> tuple[str, str]:
    """Call OpenAI API. Returns (response_text, model_version)."""
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 2000,
            },
        )
        data = resp.json()
        return data["choices"][0]["message"]["content"], data.get("model", "gpt-4o")


def _init_providers():
    if os.getenv("ANTHROPIC_API_KEY"):
        AI_PROVIDERS["claude"] = call_anthropic
    if os.getenv("OPENAI_API_KEY"):
        AI_PROVIDERS["gpt-4o"] = call_openai


_init_providers()


# ── Pydantic request bodies ──────────────────────────────────────────

class AuditTriggerRequest(BaseModel):
    models: list[str]
    prompt: str


class PublishRejectRequest(BaseModel):
    reason: str


# ── Helper: fetch & validate amendment ───────────────────────────────

ALLOWED_AUDIT_STATUSES = {"proposed", "deliberation"}


async def _get_amendment_or_404(amendment_id: int, db: AsyncSession) -> Amendment:
    result = await db.execute(select(Amendment).where(Amendment.id == amendment_id))
    amendment = result.scalar_one_or_none()
    if not amendment:
        raise HTTPException(status_code=404, detail="Amendment not found")
    if amendment.status not in ALLOWED_AUDIT_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Amendment status '{amendment.status}' not eligible for audit",
        )
    return amendment


# ── Endpoints ────────────────────────────────────────────────────────

@router.post("/admin/amendments/{amendment_id}/audit")
async def trigger_audit(
    amendment_id: int,
    body: AuditTriggerRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """Trigger AI audit for an amendment across requested models."""
    amendment = await _get_amendment_or_404(amendment_id, db)

    results = []
    for model_name in body.models:
        # Check provider exists
        provider = AI_PROVIDERS.get(model_name)
        if not provider:
            results.append({"model_name": model_name, "success": False, "error": f"Unknown provider: {model_name}"})
            continue

        # Check uniqueness: one audit per model per amendment
        existing = await db.execute(
            select(AuditResponse).where(
                AuditResponse.amendment_id == amendment.id,
                AuditResponse.model_name == model_name,
            )
        )
        if existing.scalar_one_or_none():
            results.append({"model_name": model_name, "success": False, "error": "Already audited by this model"})
            continue

        # Call provider
        try:
            response_text, model_version = await provider(body.prompt)
        except Exception as exc:
            print(f"[AUDIT ERROR] {model_name}: {exc}")
            results.append({"model_name": model_name, "success": False, "error": "AI provider call failed"})
            continue

        audit = AuditResponse(
            amendment_id=amendment.id,
            model_name=model_name,
            model_version=model_version,
            prompt_used=body.prompt,
            response_text=response_text,
            published=False,
        )
        db.add(audit)
        await db.flush()
        results.append({"model_name": model_name, "success": True})

    await db.commit()
    return results


@router.post("/admin/amendments/{amendment_id}/audit/{audit_id}/publish")
async def publish_audit(
    amendment_id: int,
    audit_id: int,
    body: PublishRejectRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """Publish an audit response (make it visible publicly)."""
    result = await db.execute(
        select(AuditResponse).where(
            AuditResponse.id == audit_id,
            AuditResponse.amendment_id == amendment_id,
        )
    )
    audit = result.scalar_one_or_none()
    if not audit:
        raise HTTPException(status_code=404, detail="Audit response not found")
    if audit.published:
        raise HTTPException(status_code=409, detail="Already published")

    audit.published = True
    audit.publication_decision_logged = True

    action = AdminAction(
        amendment_id=amendment_id,
        action="audit_published",
        via="audit",
        reason=body.reason,
        audit_response_id=audit_id,
    )
    db.add(action)
    await db.commit()

    return {"message": "published"}


@router.post("/admin/amendments/{amendment_id}/audit/{audit_id}/reject")
async def reject_audit(
    amendment_id: int,
    audit_id: int,
    body: PublishRejectRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """Reject an audit response (keep unpublished, log decision)."""
    result = await db.execute(
        select(AuditResponse).where(
            AuditResponse.id == audit_id,
            AuditResponse.amendment_id == amendment_id,
        )
    )
    audit = result.scalar_one_or_none()
    if not audit:
        raise HTTPException(status_code=404, detail="Audit response not found")

    audit.publication_decision_logged = True

    action = AdminAction(
        amendment_id=amendment_id,
        action="audit_rejected",
        via="audit",
        reason=body.reason,
        audit_response_id=audit_id,
    )
    db.add(action)
    await db.commit()

    return {"message": "rejected"}


@router.get("/amendments/{amendment_id}/audit-responses")
async def public_audit_responses(
    amendment_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Return only published audit responses (public)."""
    result = await db.execute(
        select(AuditResponse).where(
            AuditResponse.amendment_id == amendment_id,
            AuditResponse.published == True,
        )
    )
    responses = result.scalars().all()

    return [
        {
            "id": r.id,
            "model_name": r.model_name,
            "model_version": r.model_version,
            "prompt_used": r.prompt_used,
            "response_text": r.response_text,
            "audited_at": r.audited_at.isoformat() if r.audited_at else None,
        }
        for r in responses
    ]


@router.get("/admin/amendments/{amendment_id}/audit-responses")
async def admin_audit_responses(
    amendment_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """Return ALL audit responses including unpublished (admin)."""
    result = await db.execute(
        select(AuditResponse).where(AuditResponse.amendment_id == amendment_id)
    )
    responses = result.scalars().all()

    return [
        {
            "id": r.id,
            "model_name": r.model_name,
            "model_version": r.model_version,
            "prompt_used": r.prompt_used,
            "response_text": r.response_text,
            "audited_at": r.audited_at.isoformat() if r.audited_at else None,
            "published": r.published,
            "publication_decision_logged": r.publication_decision_logged,
        }
        for r in responses
    ]
