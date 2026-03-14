import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, Text, ARRAY
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from database import Base, get_db
from models import Signature, Amendment, AmendmentSupport, DraftShareToken, DraftComment
from auth_dependencies import create_jwt, COOKIE_NAME

# Patch ARRAY columns to Text for SQLite compatibility
for col in Amendment.__table__.columns:
    if isinstance(col.type, ARRAY):
        col.type = Text()


@pytest_asyncio.fixture
async def setup():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        # Alice — proposal author
        alice = Signature(
            id=1, pseudo="Alice", email="alice@test.com",
            lang="fr", token="tok_alice", confirmed=True,
            confirmed_at=datetime.now(timezone.utc),
        )
        # Bob — supporter
        bob = Signature(
            id=2, pseudo="Bob", email="bob@test.com",
            lang="fr", token="tok_bob", confirmed=True,
            confirmed_at=datetime.now(timezone.utc),
        )
        session.add_all([alice, bob])
        await session.commit()

    # Import app after patching
    from main import app
    # Register proposals router if not already registered
    from proposals import router as proposals_router
    # Check if router is already included
    already_included = any(
        getattr(r, "prefix", None) == "/proposals"
        for r in app.router.routes
    )
    if not already_included:
        app.include_router(proposals_router)

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db

    alice_jwt = create_jwt(signer_id=1, display_name="Alice")
    bob_jwt = create_jwt(signer_id=2, display_name="Bob")
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport, base_url="http://test",
        cookies={COOKIE_NAME: alice_jwt}
    ) as alice_client:
        async with AsyncClient(
            transport=transport, base_url="http://test",
            cookies={COOKIE_NAME: bob_jwt}
        ) as bob_client:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as anon_client:
                yield alice_client, bob_client, anon_client, session_factory

    app.dependency_overrides.clear()
    await engine.dispose()


DRAFT_BODY = {
    "amendment_type": "modification",
    "title": "Improve transparency",
    "principle_id": "transparence",
    "text_after": "New improved text for transparency principle",
    "motivation": "The current text is unclear and needs improvement",
    "tier": "mineur",
    "submission_language": "fr",
}


@pytest.mark.asyncio
async def test_create_draft(setup):
    alice, _, _, sf = setup
    resp = await alice.post("/proposals/drafts", json=DRAFT_BODY)
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"].startswith("P")
    assert data["status"] == "draft"
    assert data["tier"] == "mineur"


@pytest.mark.asyncio
async def test_list_drafts(setup):
    alice, _, _, sf = setup
    await alice.post("/proposals/drafts", json=DRAFT_BODY)
    resp = await alice.get("/proposals/drafts")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["drafts"]) >= 1
    assert data["drafts"][0]["title"] == "Improve transparency"


@pytest.mark.asyncio
async def test_max_5_drafts(setup):
    alice, _, _, sf = setup
    for i in range(5):
        body = {**DRAFT_BODY, "title": f"Draft {i+1}"}
        resp = await alice.post("/proposals/drafts", json=body)
        assert resp.status_code == 200, f"Draft {i+1} failed: {resp.text}"

    # 6th should fail
    body = {**DRAFT_BODY, "title": "Draft 6"}
    resp = await alice.post("/proposals/drafts", json=body)
    assert resp.status_code == 409
    assert "Maximum 5" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_submit_draft(setup):
    alice, _, _, sf = setup
    resp = await alice.post("/proposals/drafts", json=DRAFT_BODY)
    draft_id = resp.json()["id"]

    resp = await alice.post(f"/proposals/drafts/{draft_id}/submit")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "proposed"
    assert "expires_at" in data
    assert data["deliberation_duration_days"] == 14  # mineur

    # Verify in DB
    async with sf() as session:
        result = await session.execute(select(Amendment).where(Amendment.id == draft_id))
        a = result.scalar_one()
        assert a.status == "proposed"
        assert a.expires_at is not None


@pytest.mark.asyncio
async def test_addition_forces_fondateur(setup):
    alice, _, _, sf = setup
    body = {
        "amendment_type": "addition",
        "title": "New principle of solidarity",
        "text_after": "All members shall act in solidarity",
        "motivation": "We need a solidarity principle",
        "tier": "mineur",  # should be forced to fondateur
        "submission_language": "fr",
    }
    resp = await alice.post("/proposals/drafts", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["tier"] == "fondateur"

    # Submit and verify
    draft_id = data["id"]
    resp = await alice.post(f"/proposals/drafts/{draft_id}/submit")
    assert resp.status_code == 200
    assert resp.json()["deliberation_duration_days"] == 30  # fondateur


@pytest.mark.asyncio
async def test_support_proposal(setup):
    alice, bob, _, sf = setup

    # Alice creates and submits
    resp = await alice.post("/proposals/drafts", json=DRAFT_BODY)
    draft_id = resp.json()["id"]
    await alice.post(f"/proposals/drafts/{draft_id}/submit")

    # Bob supports
    resp = await bob.post(f"/proposals/{draft_id}/support", json={"comment": "Great idea"})
    assert resp.status_code == 200
    assert resp.json()["message"] == "supported"

    # Alice cannot support her own
    resp = await alice.post(f"/proposals/{draft_id}/support", json={})
    assert resp.status_code == 409
    assert "own proposal" in resp.json()["detail"]

    # Bob cannot support twice
    resp = await bob.post(f"/proposals/{draft_id}/support", json={})
    assert resp.status_code == 409
    assert "Already supported" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_withdraw_proposal(setup):
    alice, _, _, sf = setup
    resp = await alice.post("/proposals/drafts", json=DRAFT_BODY)
    draft_id = resp.json()["id"]
    await alice.post(f"/proposals/drafts/{draft_id}/submit")

    resp = await alice.post(f"/proposals/{draft_id}/withdraw")
    assert resp.status_code == 200
    assert resp.json()["message"] == "withdrawn"

    async with sf() as session:
        result = await session.execute(select(Amendment).where(Amendment.id == draft_id))
        a = result.scalar_one()
        assert a.status == "withdrawn"
        assert a.withdrawn_at is not None


@pytest.mark.asyncio
async def test_share_draft(setup):
    alice, _, anon, sf = setup
    resp = await alice.post("/proposals/drafts", json=DRAFT_BODY)
    draft_id = resp.json()["id"]

    # Generate share token
    resp = await alice.post(f"/proposals/drafts/{draft_id}/share")
    assert resp.status_code == 200
    token = resp.json()["token"]

    # Anon reads via token
    resp = await anon.get(f"/proposals/shared/{token}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["draft"]["title"] == "Improve transparency"

    # Anon adds comment
    resp = await anon.post(f"/proposals/shared/{token}/comments", json={
        "author_name": "Reviewer",
        "comment": "Looks good to me",
    })
    assert resp.status_code == 200

    # Verify comment appears
    resp = await anon.get(f"/proposals/shared/{token}")
    assert len(resp.json()["comments"]) == 1


@pytest.mark.asyncio
async def test_public_amendments_list(setup):
    alice, _, anon, sf = setup

    # Create and submit a draft so it becomes proposed (non-draft)
    resp = await alice.post("/proposals/drafts", json=DRAFT_BODY)
    draft_id = resp.json()["id"]
    await alice.post(f"/proposals/drafts/{draft_id}/submit")

    resp = await anon.get("/proposals/public")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["amendments"]) >= 1
    a = data["amendments"][0]
    assert a["status"] == "proposed"
    assert "id" in a
    assert "code" in a
    assert "tier" in a

    # Filter by status
    resp = await anon.get("/proposals/public?status=proposed")
    assert resp.status_code == 200
    assert len(resp.json()["amendments"]) >= 1

    # Filter by non-existent status returns empty
    resp = await anon.get("/proposals/public?status=deliberation")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_charter_principles(setup):
    _, _, anon, _ = setup
    resp = await anon.get("/proposals/charter/principles")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["principles"]) == 8
    ids = [p["id"] for p in data["principles"]]
    assert "bienveillance" in ids
    assert "deliberation" in ids


@pytest.mark.asyncio
async def test_delete_draft(setup):
    alice, _, _, sf = setup
    resp = await alice.post("/proposals/drafts", json=DRAFT_BODY)
    draft_id = resp.json()["id"]

    resp = await alice.delete(f"/proposals/drafts/{draft_id}")
    assert resp.status_code == 200

    resp = await alice.get("/proposals/drafts")
    assert len(resp.json()["drafts"]) == 0


@pytest.mark.asyncio
async def test_update_draft(setup):
    alice, _, _, sf = setup
    resp = await alice.post("/proposals/drafts", json=DRAFT_BODY)
    draft_id = resp.json()["id"]

    resp = await alice.put(f"/proposals/drafts/{draft_id}", json={"title": "Updated title"})
    assert resp.status_code == 200

    resp = await alice.get("/proposals/drafts")
    assert resp.json()["drafts"][0]["title"] == "Updated title"


@pytest.mark.asyncio
async def test_unauthenticated_cannot_create_draft(setup):
    _, _, anon, _ = setup
    resp = await anon.post("/proposals/drafts", json=DRAFT_BODY)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_supports_list_public(setup):
    alice, bob, anon, sf = setup

    resp = await alice.post("/proposals/drafts", json=DRAFT_BODY)
    draft_id = resp.json()["id"]
    await alice.post(f"/proposals/drafts/{draft_id}/submit")

    await bob.post(f"/proposals/{draft_id}/support", json={"comment": "I support this"})

    resp = await anon.get(f"/proposals/{draft_id}/supports")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["supports"]) == 1
    assert data["supports"][0]["signer_name"] == "Bob"
