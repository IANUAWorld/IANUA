import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

from database import Base, get_db
from models import Amendment, AuditResponse, AdminAction
from audit_ia import AI_PROVIDERS

ADMIN_KEY = "test-admin-key"
ADMIN_HEADERS = {"X-Admin-Key": ADMIN_KEY}


@pytest_asyncio.fixture
async def setup(monkeypatch):
    monkeypatch.setenv("ADMIN_KEY", ADMIN_KEY)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        amendment = Amendment(
            id=1,
            code="A010",
            principle_id="transparence",
            target="principle_body",
            amendment_type="modification",
            text_before="old text",
            text_after="new text",
            motivation="improve clarity",
            source_type="community",
            phase="phase_1",
            status="proposed",
            votes_for=0,
            votes_against=0,
            votes_abstain=0,
        )
        session.add(amendment)
        await session.commit()

    # Register mock provider
    async def mock_provider(prompt: str) -> tuple[str, str]:
        return (f"Mock response to: {prompt[:50]}", "mock-v1")

    AI_PROVIDERS["mock-model"] = mock_provider

    from main import app

    # Register audit_ia router if not already registered
    from audit_ia import router as audit_router
    already_included = any(
        r.path.startswith("/admin/amendments") and "audit" in r.path
        for r in app.routes
        if hasattr(r, "path")
    )
    if not already_included:
        app.include_router(audit_router)

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, session_factory

    app.dependency_overrides.clear()
    # Clean up mock provider
    AI_PROVIDERS.pop("mock-model", None)
    await engine.dispose()


@pytest.mark.asyncio
async def test_trigger_audit(setup):
    client, sf = setup
    resp = await client.post(
        "/admin/amendments/1/audit",
        json={"models": ["mock-model"], "prompt": "Analyze this amendment"},
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["model_name"] == "mock-model"
    assert data[0]["success"] is True

    # Verify DB row
    async with sf() as session:
        result = await session.execute(select(AuditResponse).where(AuditResponse.amendment_id == 1))
        audit = result.scalar_one()
        assert audit.model_name == "mock-model"
        assert audit.model_version == "mock-v1"
        assert audit.published is False
        assert "Mock response to:" in audit.response_text


@pytest.mark.asyncio
async def test_trigger_audit_unknown_model(setup):
    client, _ = setup
    resp = await client.post(
        "/admin/amendments/1/audit",
        json={"models": ["unknown"], "prompt": "Test prompt"},
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["success"] is False
    assert "Unknown provider" in data[0]["error"]


@pytest.mark.asyncio
async def test_publish_audit(setup):
    client, sf = setup

    # First trigger an audit
    await client.post(
        "/admin/amendments/1/audit",
        json={"models": ["mock-model"], "prompt": "Analyze"},
        headers=ADMIN_HEADERS,
    )

    # Get audit id
    async with sf() as session:
        result = await session.execute(select(AuditResponse).where(AuditResponse.amendment_id == 1))
        audit_id = result.scalar_one().id

    # Publish
    resp = await client.post(
        f"/admin/amendments/1/audit/{audit_id}/publish",
        json={"reason": "Good analysis"},
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "published"

    # Verify DB
    async with sf() as session:
        result = await session.execute(select(AuditResponse).where(AuditResponse.id == audit_id))
        audit = result.scalar_one()
        assert audit.published is True
        assert audit.publication_decision_logged is True

        result = await session.execute(
            select(AdminAction).where(AdminAction.audit_response_id == audit_id)
        )
        action = result.scalar_one()
        assert action.action == "audit_published"
        assert action.via == "audit"
        assert action.reason == "Good analysis"


@pytest.mark.asyncio
async def test_publish_audit_already_published(setup):
    client, sf = setup

    await client.post(
        "/admin/amendments/1/audit",
        json={"models": ["mock-model"], "prompt": "Analyze"},
        headers=ADMIN_HEADERS,
    )

    async with sf() as session:
        result = await session.execute(select(AuditResponse).where(AuditResponse.amendment_id == 1))
        audit_id = result.scalar_one().id

    # Publish once
    await client.post(
        f"/admin/amendments/1/audit/{audit_id}/publish",
        json={"reason": "Good"},
        headers=ADMIN_HEADERS,
    )
    # Publish again -> 409
    resp = await client.post(
        f"/admin/amendments/1/audit/{audit_id}/publish",
        json={"reason": "Again"},
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_reject_audit(setup):
    client, sf = setup

    await client.post(
        "/admin/amendments/1/audit",
        json={"models": ["mock-model"], "prompt": "Analyze"},
        headers=ADMIN_HEADERS,
    )

    async with sf() as session:
        result = await session.execute(select(AuditResponse).where(AuditResponse.amendment_id == 1))
        audit_id = result.scalar_one().id

    resp = await client.post(
        f"/admin/amendments/1/audit/{audit_id}/reject",
        json={"reason": "Not relevant"},
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "rejected"

    # Verify DB
    async with sf() as session:
        result = await session.execute(select(AuditResponse).where(AuditResponse.id == audit_id))
        audit = result.scalar_one()
        assert audit.published is False
        assert audit.publication_decision_logged is True

        result = await session.execute(
            select(AdminAction).where(AdminAction.audit_response_id == audit_id)
        )
        action = result.scalar_one()
        assert action.action == "audit_rejected"
        assert action.reason == "Not relevant"


@pytest.mark.asyncio
async def test_public_audit_responses(setup):
    client, sf = setup

    # Trigger audit
    await client.post(
        "/admin/amendments/1/audit",
        json={"models": ["mock-model"], "prompt": "Analyze"},
        headers=ADMIN_HEADERS,
    )

    # Before publishing: public endpoint returns empty
    resp = await client.get("/amendments/1/audit-responses")
    assert resp.status_code == 200
    assert resp.json() == []

    # Publish
    async with sf() as session:
        result = await session.execute(select(AuditResponse).where(AuditResponse.amendment_id == 1))
        audit_id = result.scalar_one().id

    await client.post(
        f"/admin/amendments/1/audit/{audit_id}/publish",
        json={"reason": "Approved"},
        headers=ADMIN_HEADERS,
    )

    # Now public endpoint returns it
    resp = await client.get("/amendments/1/audit-responses")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["model_name"] == "mock-model"
    assert "published" not in data[0]  # public view doesn't include this field


@pytest.mark.asyncio
async def test_admin_audit_responses(setup):
    client, sf = setup

    # Trigger audit
    await client.post(
        "/admin/amendments/1/audit",
        json={"models": ["mock-model"], "prompt": "Analyze"},
        headers=ADMIN_HEADERS,
    )

    # Admin endpoint returns all (including unpublished)
    resp = await client.get(
        "/admin/amendments/1/audit-responses",
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["model_name"] == "mock-model"
    assert data[0]["published"] is False
    assert "publication_decision_logged" in data[0]


@pytest.mark.asyncio
async def test_unique_model_per_amendment(setup):
    client, _ = setup

    # First audit
    resp = await client.post(
        "/admin/amendments/1/audit",
        json={"models": ["mock-model"], "prompt": "First audit"},
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()[0]["success"] is True

    # Second audit with same model -> skipped with error
    resp = await client.post(
        "/admin/amendments/1/audit",
        json={"models": ["mock-model"], "prompt": "Second audit"},
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["success"] is False
    assert "Already audited" in data[0]["error"]


@pytest.mark.asyncio
async def test_trigger_audit_forbidden_without_admin_key(setup):
    client, _ = setup
    resp = await client.post(
        "/admin/amendments/1/audit",
        json={"models": ["mock-model"], "prompt": "Test"},
    )
    assert resp.status_code == 403
