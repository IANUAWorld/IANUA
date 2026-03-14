import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["ADMIN_KEY"] = "test-admin-key"

import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from database import Base, get_db
from models import Amendment, MagicToken, Signature

ADMIN_HEADERS = {"X-Admin-Key": "test-admin-key"}


@pytest_asyncio.fixture
async def setup():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    now = datetime.now(timezone.utc)

    async with session_factory() as session:
        # 1 expired proposal
        expired_proposal = Amendment(
            id=1, code="A010", principle_id="transparence",
            target="principle_body", amendment_type="modification",
            motivation="outdated proposal", source_type="community",
            phase="phase_2", status="proposed", tier="mineur",
            expires_at=now - timedelta(days=1),
        )

        # 1 deliberation amendment ready to close (mineur, 80% > 50%)
        delib_amendment = Amendment(
            id=2, code="A011", principle_id="transparence",
            target="principle_body", amendment_type="modification",
            motivation="improve clarity", source_type="community",
            phase="phase_2", status="deliberation", tier="mineur",
            votes_for=8, votes_against=2, votes_abstain=1,
            vote_threshold=50,
            vote_opened_at=now - timedelta(days=14),
            vote_closed_at=now - timedelta(hours=1),
        )

        # 2 confirmed signatures (for quorum)
        sig1 = Signature(
            id=1, pseudo="Alice", email="alice@test.com",
            lang="fr", token="tok1", confirmed=True,
            confirmed_at=now,
        )
        sig2 = Signature(
            id=2, pseudo="Bob", email="bob@test.com",
            lang="fr", token="tok2", confirmed=True,
            confirmed_at=now,
        )

        # 1 used MagicToken + 1 expired MagicToken
        used_token = MagicToken(
            id=1, email="alice@test.com", token="used-tok",
            used=True, expires_at=now + timedelta(hours=1),
        )
        expired_token = MagicToken(
            id=2, email="bob@test.com", token="expired-tok",
            used=False, expires_at=now - timedelta(hours=1),
        )

        session.add_all([
            expired_proposal, delib_amendment,
            sig1, sig2,
            used_token, expired_token,
        ])
        await session.commit()

    from main import app

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, session_factory

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_expire_proposals(setup):
    client, sf = setup
    resp = await client.post("/crons/expire-proposals", headers=ADMIN_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1

    async with sf() as session:
        from sqlalchemy import select
        result = await session.execute(select(Amendment).where(Amendment.id == 1))
        a = result.scalar_one()
        assert a.status == "expired"


@pytest.mark.asyncio
async def test_close_votes_ratified(setup):
    client, sf = setup
    resp = await client.post("/crons/close-votes", headers=ADMIN_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["results"][0]["status"] == "ratified"

    async with sf() as session:
        from sqlalchemy import select
        result = await session.execute(select(Amendment).where(Amendment.id == 2))
        a = result.scalar_one()
        assert a.status == "ratified"


@pytest.mark.asyncio
async def test_cleanup_tokens(setup):
    client, _ = setup
    resp = await client.post("/crons/cleanup-tokens", headers=ADMIN_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2


@pytest.mark.asyncio
async def test_crons_require_admin(setup):
    client, _ = setup
    for endpoint in [
        "/crons/expire-proposals",
        "/crons/close-votes",
        "/crons/cleanup-tokens",
    ]:
        resp = await client.post(endpoint)
        assert resp.status_code == 403, f"{endpoint} should require admin key"
