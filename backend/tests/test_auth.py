import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from database import Base, get_db
from models import Signature, MagicToken
from auth_dependencies import decode_jwt, COOKIE_NAME


@pytest_asyncio.fixture
async def setup():
    """Create test app with in-memory DB."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Seed a confirmed signer
    async with session_factory() as session:
        signer = Signature(
            id=1, pseudo="Alice", email="alice@test.com",
            lang="fr", token="old-token", confirmed=True,
            confirmed_at=datetime.now(timezone.utc),
        )
        session.add(signer)
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
async def test_magic_link_unknown_email(setup):
    client, _ = setup
    resp = await client.post("/auth/magic-link", json={"email": "unknown@test.com"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_magic_link_creates_token(setup):
    client, session_factory = setup
    resp = await client.post("/auth/magic-link", json={"email": "alice@test.com"})
    # May be 200 (email sent) or 502 (Brevo not configured in test)
    # The token should still be created in DB
    async with session_factory() as session:
        from sqlalchemy import select
        result = await session.execute(select(MagicToken).where(MagicToken.email == "alice@test.com"))
        token = result.scalar_one_or_none()
        assert token is not None
        assert not token.used


@pytest.mark.asyncio
async def test_verify_sets_cookie(setup):
    client, session_factory = setup

    async with session_factory() as session:
        mt = MagicToken(
            email="alice@test.com",
            token="test-verify-token",
            used=False,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )
        session.add(mt)
        await session.commit()

    resp = await client.get("/auth/verify/test-verify-token", follow_redirects=False)
    assert resp.status_code == 307
    assert COOKIE_NAME in resp.cookies

    # Token should be marked used
    async with session_factory() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(MagicToken).where(MagicToken.token == "test-verify-token")
        )
        token = result.scalar_one()
        assert token.used


@pytest.mark.asyncio
async def test_verify_used_token_rejected(setup):
    client, session_factory = setup

    async with session_factory() as session:
        mt = MagicToken(
            email="alice@test.com",
            token="used-token",
            used=True,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )
        session.add(mt)
        await session.commit()

    resp = await client.get("/auth/verify/used-token", follow_redirects=False)
    assert resp.status_code == 307
    assert "error=used" in resp.headers.get("location", "")


@pytest.mark.asyncio
async def test_verify_expired_token_rejected(setup):
    client, session_factory = setup

    async with session_factory() as session:
        mt = MagicToken(
            email="alice@test.com",
            token="expired-token",
            used=False,
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        session.add(mt)
        await session.commit()

    resp = await client.get("/auth/verify/expired-token", follow_redirects=False)
    assert resp.status_code == 307
    assert "error=expired" in resp.headers.get("location", "")


@pytest.mark.asyncio
async def test_auth_me_authenticated(setup):
    client, session_factory = setup

    async with session_factory() as session:
        mt = MagicToken(
            email="alice@test.com",
            token="me-test-token",
            used=False,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )
        session.add(mt)
        await session.commit()

    resp = await client.get("/auth/verify/me-test-token", follow_redirects=False)

    # Extract the JWT cookie value from the Set-Cookie header
    cookie_value = resp.cookies.get(COOKIE_NAME)
    assert cookie_value is not None, "JWT cookie should be set after verify"

    # Set it on the client for the next request
    client.cookies.set(COOKIE_NAME, cookie_value)
    resp2 = await client.get("/auth/me")
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["name"] == "Alice"
    assert data["sub"] == 1

    # Clean up client cookies for other tests
    client.cookies.clear()


@pytest.mark.asyncio
async def test_auth_me_unauthenticated(setup):
    client, _ = setup
    resp = await client.get("/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_logout_clears_cookie(setup):
    client, _ = setup
    resp = await client.post("/auth/logout")
    assert resp.status_code == 200
    assert COOKIE_NAME in resp.headers.get("set-cookie", "")
