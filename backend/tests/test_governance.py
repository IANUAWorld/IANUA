import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["ADMIN_KEY"] = "test-admin-key"

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from database import Base, get_db
from models import Signature, Amendment, TierChallenge, ContentReport, AdminAction
from auth_dependencies import create_jwt, COOKIE_NAME


@pytest_asyncio.fixture
async def setup():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        alice = Signature(
            id=1, pseudo="Alice", email="alice@test.com",
            lang="fr", token="tok_alice", confirmed=True,
            confirmed_at=datetime.now(timezone.utc),
        )
        bob = Signature(
            id=2, pseudo="Bob", email="bob@test.com",
            lang="fr", token="tok_bob", confirmed=True,
            confirmed_at=datetime.now(timezone.utc),
        )
        charlie = Signature(
            id=3, pseudo="Charlie", email="charlie@test.com",
            lang="fr", token="tok_charlie", confirmed=True,
            confirmed_at=datetime.now(timezone.utc),
        )
        amendment = Amendment(
            id=1, code="A010", principle_id="transparence",
            target="principle_body", amendment_type="modification",
            text_before="old text", text_after="new text",
            motivation="improve clarity", source_type="community",
            phase="phase_2", status="proposed",
            tier="mineur",
            votes_for=0, votes_against=0, votes_abstain=0,
            author_id=1,
        )
        session.add_all([alice, bob, charlie, amendment])
        await session.commit()

    from main import app
    from governance import router
    # Ensure governance router is included
    if router not in [r for r in app.router.routes]:
        app.include_router(router)

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db

    jwt_bob = create_jwt(signer_id=2, display_name="Bob")
    jwt_charlie = create_jwt(signer_id=3, display_name="Charlie")

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test",
        cookies={COOKIE_NAME: jwt_bob}
    ) as bob_client:
        async with AsyncClient(
            transport=transport, base_url="http://test",
            cookies={COOKIE_NAME: jwt_charlie}
        ) as charlie_client:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as anon_client:
                yield bob_client, charlie_client, anon_client, session_factory

    app.dependency_overrides.clear()
    await engine.dispose()


# ── Tier challenges ──────────────────────────────

@pytest.mark.asyncio
async def test_challenge_tier(setup):
    bob, _, _, _ = setup
    resp = await bob.post("/proposals/1/challenge-tier", json={"suggested_tier": "substantiel"})
    assert resp.status_code == 200
    assert resp.json()["message"] == "Challenge recorded"


@pytest.mark.asyncio
async def test_challenge_tier_already_challenged(setup):
    bob, _, _, _ = setup
    await bob.post("/proposals/1/challenge-tier", json={"suggested_tier": "substantiel"})
    resp = await bob.post("/proposals/1/challenge-tier", json={"suggested_tier": "fondateur"})
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_challenge_only_upward(setup):
    bob, _, _, _ = setup
    resp = await bob.post("/proposals/1/challenge-tier", json={"suggested_tier": "mineur"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_challenge_convergence_auto_requalify(setup):
    bob, charlie, _, sf = setup

    # Create a 4th signer for the 3rd challenge
    async with sf() as session:
        dave = Signature(
            id=4, pseudo="Dave", email="dave@test.com",
            lang="fr", token="tok_dave", confirmed=True,
            confirmed_at=datetime.now(timezone.utc),
        )
        session.add(dave)
        await session.commit()

    jwt_dave = create_jwt(signer_id=4, display_name="Dave")

    from main import app
    transport = ASGITransport(app=app)

    # Bob challenges to fondateur
    resp = await bob.post("/proposals/1/challenge-tier", json={"suggested_tier": "fondateur"})
    assert resp.status_code == 200

    # Charlie challenges to fondateur
    resp = await charlie.post("/proposals/1/challenge-tier", json={"suggested_tier": "fondateur"})
    assert resp.status_code == 200

    # Dave challenges to fondateur (3rd convergent challenge)
    async with AsyncClient(
        transport=transport, base_url="http://test",
        cookies={COOKIE_NAME: jwt_dave}
    ) as dave_client:
        resp = await dave_client.post("/proposals/1/challenge-tier", json={"suggested_tier": "fondateur"})
        assert resp.status_code == 200

    # Verify amendment was auto-requalified
    async with sf() as session:
        from sqlalchemy import select
        result = await session.execute(select(Amendment).where(Amendment.id == 1))
        a = result.scalar_one()
        assert a.tier == "fondateur"
        assert a.tier_requalified is True
        assert a.tier_requalified_by == "auto"
        assert a.tier_original == "mineur"

        # Verify AdminAction was logged
        result = await session.execute(select(AdminAction).where(AdminAction.amendment_id == 1))
        actions = result.scalars().all()
        assert len(actions) >= 1
        assert any(a.action == "tier_requalified" for a in actions)


# ── Content reports ──────────────────────────────

@pytest.mark.asyncio
async def test_report_proposal(setup):
    bob, _, _, _ = setup
    resp = await bob.post("/proposals/1/report", json={"category": "spam"})
    assert resp.status_code == 200
    assert resp.json()["message"] == "Report recorded"


@pytest.mark.asyncio
async def test_report_already_reported(setup):
    bob, _, _, _ = setup
    await bob.post("/proposals/1/report", json={"category": "spam"})
    resp = await bob.post("/proposals/1/report", json={"category": "hors_charte"})
    assert resp.status_code == 409


# ── Admin actions ────────────────────────────────

@pytest.mark.asyncio
async def test_admin_delete(setup):
    _, _, anon, sf = setup
    resp = await anon.post(
        "/admin/amendments/1/delete",
        json={"reason": "Violation of charter", "via": "direct_action"},
        headers={"X-Admin-Key": "test-admin-key"},
    )
    assert resp.status_code == 200

    async with sf() as session:
        from sqlalchemy import select
        result = await session.execute(select(Amendment).where(Amendment.id == 1))
        a = result.scalar_one()
        assert a.status == "deleted"

        result = await session.execute(select(AdminAction).where(AdminAction.amendment_id == 1))
        action = result.scalar_one()
        assert action.action == "deleted"
        assert action.reason == "Violation of charter"


# ── Transparency ─────────────────────────────────

@pytest.mark.asyncio
async def test_transparency_public(setup):
    _, _, anon, _ = setup
    resp = await anon.get("/transparency/actions")
    assert resp.status_code == 200
    data = resp.json()
    assert "actions" in data
