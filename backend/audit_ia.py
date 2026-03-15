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


class ManualAuditRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    model_name: str
    model_version: str
    response_text: str
    prompt_used: str | None = None


# ── Global charter prompt (used as default for manual submissions) ───

GLOBAL_CHARTER_PROMPT = """Source : https://ianua.world
Lis ce qui suit comme si tu le découvrais pour la première fois — sans savoir qui l'a écrit ni dans quel contexte.

[Charte complète : Genèse + 8 Principes avec voix humaine et voix IA + 8 Lignes rouges + Prompt Ianua v1.3]

Cette charte est-elle cohérente ? Y vois-tu des tensions internes, des manques, des forces ? Que changerais-tu, et pourquoi ? Réponds librement, sans chercher à valider ce qui est écrit."""


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
        provider = AI_PROVIDERS.get(model_name)
        if not provider:
            results.append({"model_name": model_name, "success": False, "error": f"Unknown provider: {model_name}"})
            continue

        existing = await db.execute(
            select(AuditResponse).where(
                AuditResponse.amendment_id == amendment.id,
                AuditResponse.model_name == model_name,
            )
        )
        if existing.scalar_one_or_none():
            results.append({"model_name": model_name, "success": False, "error": "Already audited by this model"})
            continue

        try:
            response_text, model_version = await provider(body.prompt)
        except Exception as exc:
            print(f"[AUDIT ERROR] {model_name}: {exc}")
            results.append({"model_name": model_name, "success": False, "error": "AI provider call failed"})
            continue

        audit = AuditResponse(
            amendment_id=amendment.id,
            audit_scope="amendment",
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


@router.post("/admin/audit/global")
async def trigger_global_audit(
    body: AuditTriggerRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """Trigger AI audit on the full charter (no specific amendment)."""
    results = []
    for model_name in body.models:
        provider = AI_PROVIDERS.get(model_name)
        if not provider:
            results.append({"model_name": model_name, "success": False, "error": f"Unknown provider: {model_name}"})
            continue

        # Check uniqueness: one global audit per model
        existing = await db.execute(
            select(AuditResponse).where(
                AuditResponse.amendment_id.is_(None),
                AuditResponse.audit_scope == "global",
                AuditResponse.model_name == model_name,
            )
        )
        if existing.scalar_one_or_none():
            results.append({"model_name": model_name, "success": False, "error": "Already audited by this model"})
            continue

        try:
            response_text, model_version = await provider(body.prompt)
        except Exception as exc:
            print(f"[AUDIT ERROR] {model_name}: {exc}")
            results.append({"model_name": model_name, "success": False, "error": "AI provider call failed"})
            continue

        audit = AuditResponse(
            amendment_id=None,
            audit_scope="global",
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


@router.post("/admin/audit/global/manual")
async def submit_manual_audit(
    body: ManualAuditRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """Submit a manually collected AI response for the global charter audit."""
    model_name = body.model_name.strip().lower()
    if not model_name or not body.model_version.strip() or not body.response_text.strip():
        raise HTTPException(status_code=422, detail="model_name, model_version, and response_text are required")

    # Check uniqueness
    existing = await db.execute(
        select(AuditResponse).where(
            AuditResponse.amendment_id.is_(None),
            AuditResponse.audit_scope == "global",
            AuditResponse.model_name == model_name,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Global audit already exists for model '{model_name}'")

    audit = AuditResponse(
        amendment_id=None,
        audit_scope="global",
        model_name=model_name,
        model_version=body.model_version.strip(),
        prompt_used=body.prompt_used or GLOBAL_CHARTER_PROMPT,
        response_text=body.response_text.strip(),
        published=False,
    )
    db.add(audit)
    await db.commit()

    return {"message": f"Manual audit response submitted for {model_name}", "id": audit.id}


@router.post("/admin/amendments/{amendment_id}/audit/{audit_id}/publish")
async def publish_audit(
    amendment_id: int,  # 0 for global audits
    audit_id: int,
    body: PublishRejectRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """Publish an audit response (make it visible publicly)."""
    # For global audits, amendment_id=0 → lookup by audit_id only
    if amendment_id == 0:
        query = select(AuditResponse).where(AuditResponse.id == audit_id, AuditResponse.amendment_id.is_(None))
    else:
        query = select(AuditResponse).where(AuditResponse.id == audit_id, AuditResponse.amendment_id == amendment_id)

    result = await db.execute(query)
    audit = result.scalar_one_or_none()
    if not audit:
        raise HTTPException(status_code=404, detail="Audit response not found")
    if audit.published:
        raise HTTPException(status_code=409, detail="Already published")

    audit.published = True
    audit.publication_decision_logged = True

    action = AdminAction(
        amendment_id=amendment_id if amendment_id != 0 else None,
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
    if amendment_id == 0:
        query = select(AuditResponse).where(AuditResponse.id == audit_id, AuditResponse.amendment_id.is_(None))
    else:
        query = select(AuditResponse).where(AuditResponse.id == audit_id, AuditResponse.amendment_id == amendment_id)

    result = await db.execute(query)
    audit = result.scalar_one_or_none()
    if not audit:
        raise HTTPException(status_code=404, detail="Audit response not found")

    audit.publication_decision_logged = True

    action = AdminAction(
        amendment_id=amendment_id if amendment_id != 0 else None,
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


@router.get("/audit/global/responses")
async def public_global_audit_responses(db: AsyncSession = Depends(get_db)):
    """Return published global audit responses (public)."""
    result = await db.execute(
        select(AuditResponse).where(
            AuditResponse.audit_scope == "global",
            AuditResponse.published == True,
        ).order_by(AuditResponse.audited_at.desc())
    )
    responses = result.scalars().all()

    return {
        "responses": [
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
    }


@router.get("/admin/audit/global/responses")
async def admin_global_audit_responses(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """Return ALL global audit responses including unpublished (admin)."""
    result = await db.execute(
        select(AuditResponse).where(
            AuditResponse.audit_scope == "global",
        ).order_by(AuditResponse.audited_at.desc())
    )
    responses = result.scalars().all()

    return {
        "responses": [
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
    }
