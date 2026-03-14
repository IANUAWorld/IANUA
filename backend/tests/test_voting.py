import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from database import Base, get_db
from models import Signature, Amendment, AmendmentVote, VoteHistory
from auth_dependencies import create_jwt, COOKIE_NAME


@pytest_asyncio.fixture
async def setup():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        signer = Signature(
            id=1, pseudo="Alice", email="alice@test.com",
            lang="fr", token="tok", confirmed=True,
            confirmed_at=datetime.now(timezone.utc),
        )
        amendment = Amendment(
            id=1, code="A005", principle_id="transparence",
            target="principle_body", amendment_type="modification",
            text_before="old text", text_after="new text",
            motivation="improve clarity", source_type="community",
            phase="phase_2", status="deliberation",
            votes_for=0, votes_against=0, votes_abstain=0,
            vote_threshold=50,
            vote_opened_at=datetime.now(timezone.utc) - timedelta(days=1),
            vote_closed_at=datetime.now(timezone.utc) + timedelta(days=13),
        )
        session.add_all([signer, amendment])
        await session.commit()

    from main import app

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db

    jwt = create_jwt(signer_id=1, display_name="Alice")
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test",
        cookies={COOKIE_NAME: jwt}
    ) as auth_client:
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as anon_client:
            yield auth_client, anon_client, session_factory

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_voting_amendments(setup):
    _, anon, _ = setup
    resp = await anon.get("/amendments/voting")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["amendments"]) == 1
    assert data["amendments"][0]["code"] == "A005"


@pytest.mark.asyncio
async def test_submit_vote(setup):
    auth, _, sf = setup
    resp = await auth.post("/amendments/1/vote", json={"vote": "FOR"})
    assert resp.status_code == 200

    async with sf() as session:
        from sqlalchemy import select
        result = await session.execute(select(Amendment).where(Amendment.id == 1))
        a = result.scalar_one()
        assert a.votes_for == 1


@pytest.mark.asyncio
async def test_submit_vote_unauthenticated(setup):
    _, anon, _ = setup
    resp = await anon.post("/amendments/1/vote", json={"vote": "FOR"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_modify_vote_creates_history(setup):
    auth, _, sf = setup
    await auth.post("/amendments/1/vote", json={"vote": "FOR", "comment": "good"})
    resp = await auth.post("/amendments/1/vote", json={"vote": "AGAINST", "comment": "changed mind"})
    assert resp.status_code == 200

    async with sf() as session:
        from sqlalchemy import select
        result = await session.execute(select(VoteHistory))
        history = result.scalars().all()
        assert len(history) >= 1
        latest = history[-1]
        assert latest.previous_vote == "FOR"
        assert latest.previous_comment == "good"

        result = await session.execute(select(Amendment).where(Amendment.id == 1))
        a = result.scalar_one()
        assert a.votes_against >= 1


@pytest.mark.asyncio
async def test_get_votes_public(setup):
    auth, anon, _ = setup
    await auth.post("/amendments/1/vote", json={"vote": "FOR", "comment": "I agree"})
    resp = await anon.get("/amendments/1/votes")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["votes"]) >= 1
    vote = data["votes"][0]
    assert vote["voter_name"] == "Alice"
    assert vote["vote"] in ("FOR", "AGAINST", "ABSTAIN")


@pytest.mark.asyncio
async def test_invalid_vote_value(setup):
    auth, _, _ = setup
    resp = await auth.post("/amendments/1/vote", json={"vote": "INVALID"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_add_reaction_on_motivation(setup):
    auth, anon, _ = setup
    await auth.post("/amendments/1/vote", json={"vote": "FOR", "comment": "Good change"})

    resp = await anon.get("/amendments/1/votes")
    vote_id = resp.json()["votes"][0]["id"]

    resp = await auth.post(
        f"/amendments/1/votes/{vote_id}/reactions",
        json={"reaction_type": "pertinent"},
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "added"


@pytest.mark.asyncio
async def test_get_reactions_public(setup):
    auth, anon, _ = setup
    await auth.post("/amendments/1/vote", json={"vote": "FOR", "comment": "Good"})
    resp = await anon.get("/amendments/1/votes")
    vote_id = resp.json()["votes"][0]["id"]

    await auth.post(f"/amendments/1/votes/{vote_id}/reactions", json={"reaction_type": "pertinent"})

    resp = await anon.get(f"/amendments/1/votes/{vote_id}/reactions")
    assert resp.status_code == 200
    data = resp.json()
    assert data["pertinent"] >= 1
