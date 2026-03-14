# Plan 1 — Auth Magic Link + Vote Communautaire

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre aux signataires verifies de voter Pour/Contre/Abstention sur les amendements en deliberation, avec authentification par magic link email.

**Architecture:** Nouvelle migration Alembic pour les tables `magic_tokens` et `vote_history`. Nouveaux modules backend `backend/auth.py` (routes auth) et `backend/voting.py` (routes vote) inclus dans `main.py` via `app.include_router()`. Nouvelle page `frontend/vote.html`. Modification de `gouvernance.html` pour les badges de vote.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic + PyJWT + Brevo HTTP API + vanilla JS

**Specs:** `docs/superpowers/specs/2026-03-14-community-voting-design.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `backend/auth.py` | Routes auth magic link: send, verify, logout. JWT creation/validation helper. |
| `backend/voting.py` | Routes vote: list amendments in deliberation, get votes, submit/modify vote, vote history, reactions on motivations |
| `backend/auth_dependencies.py` | JWT decode dependency, `get_current_signer` helper |
| `frontend/vote.html` | Page de vote: auth UI, cartes amendements, boutons vote, resultats temps reel, motivations |
| `backend/alembic/versions/006_magic_tokens_vote_history.py` | Migration: tables `magic_tokens`, `vote_history`, colonnes ajoutees a `amendments` |
| `backend/tests/test_auth.py` | Tests auth: magic link send, verify, token usage unique, expiration, logout |
| `backend/tests/test_voting.py` | Tests vote: submit, modify, history, counters, access control |
| `backend/tests/conftest.py` | Fixtures pytest: app client, db session, test signer |

### Modified Files

| File | Changes |
|------|---------|
| `backend/main.py` | Include routers auth + voting. Add `allow_credentials=True` au CORS. |
| `backend/models.py` | Ajouter models `MagicToken`, `VoteHistory`. Ajouter colonnes `Amendment` (`rejection_reason`). |
| `backend/email_service.py` | Ajouter template magic link (FR/EN/ES) |
| `backend/requirements.txt` | Ajouter `PyJWT`, `pytest`, `pytest-asyncio`, `httpx` (test client) |
| `frontend/gouvernance.html` | Ajouter badges "Voter →" + compteurs + date cloture sur amendements en deliberation |

---

## Chunk 1: Fondations — Dependencies, Models, Migration

### Task 1: Ajouter les dependances

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Ajouter PyJWT et deps de test**

```
# Ajouter a la fin de requirements.txt:
PyJWT==2.8.0
pytest==8.2.0
pytest-asyncio==0.23.7
aiosqlite==0.20.0
```

- [ ] **Step 2: Installer les dependances**

Run: `cd backend && pip install -r requirements.txt`
Expected: Successfully installed PyJWT pytest pytest-asyncio aiosqlite

- [ ] **Step 3: Commit**

```bash
git add backend/requirements.txt
git commit -m "deps: add PyJWT, pytest, pytest-asyncio, aiosqlite"
```

---

### Task 2: Ajouter les models SQLAlchemy

**Files:**
- Modify: `backend/models.py`

Note: The existing `rejected_reason` column on `Amendment` (line 80 of models.py) serves the same purpose as the spec's `rejection_reason`. We reuse it as-is — no rename needed.

- [ ] **Step 1: Write failing test — MagicToken model import**

Create `backend/tests/__init__.py` (empty) and `backend/tests/conftest.py`:

```python
# backend/tests/conftest.py
import asyncio
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from database import Base
from models import (
    Subscriber, Comment, Reaction, Amendment, AmendmentVote,
    Signature, MagicToken, VoteHistory
)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()
```

Create `backend/tests/test_models.py`:

```python
# backend/tests/test_models.py
from models import MagicToken, VoteHistory


def test_magic_token_model_exists():
    assert MagicToken.__tablename__ == "magic_tokens"


def test_vote_history_model_exists():
    assert VoteHistory.__tablename__ == "vote_history"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'MagicToken'`

- [ ] **Step 3: Write MagicToken and VoteHistory models**

Add to `backend/models.py` after the `AmendmentVote` class:

```python
class MagicToken(Base):
    __tablename__ = "magic_tokens"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False, index=True)
    token = Column(String(64), unique=True, nullable=False, index=True)
    used = Column(Boolean, default=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class VoteHistory(Base):
    __tablename__ = "vote_history"

    id = Column(Integer, primary_key=True, index=True)
    vote_id = Column(Integer, ForeignKey("amendment_votes.id", ondelete="CASCADE"), nullable=False, index=True)
    previous_vote = Column(String(10), nullable=False)  # FOR / AGAINST / ABSTAIN
    previous_comment = Column(Text, nullable=True)
    changed_at = Column(DateTime, server_default=func.now())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/models.py backend/tests/
git commit -m "feat: add MagicToken and VoteHistory SQLAlchemy models"
```

---

### Task 3: Ecrire la migration Alembic

**Files:**
- Create: `backend/alembic/versions/006_magic_tokens_vote_history.py`

- [ ] **Step 1: Ecrire la migration**

```python
# backend/alembic/versions/006_magic_tokens_vote_history.py
"""Add magic_tokens, vote_history tables and rejection_reason column.

Revision ID: 006
Revises: 005
"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade():
    # magic_tokens
    op.create_table(
        "magic_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(255), nullable=False, index=True),
        sa.Column("token", sa.String(64), unique=True, nullable=False, index=True),
        sa.Column("used", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # vote_history
    op.create_table(
        "vote_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("vote_id", sa.Integer(), sa.ForeignKey("amendment_votes.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("previous_vote", sa.String(10), nullable=False),
        sa.Column("previous_comment", sa.Text(), nullable=True),
        sa.Column("changed_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # Note: `rejected_reason` (Text, nullable) already exists on `amendments` table.
    # The spec calls it `rejection_reason` but we reuse the existing column `rejected_reason`.
    # No migration needed for this column.


def downgrade():
    op.drop_table("vote_history")
    op.drop_table("magic_tokens")
```

- [ ] **Step 2: Verifier la syntaxe**

Run: `cd backend && python -c "import alembic.versions" 2>&1 || python -c "exec(open('alembic/versions/006_magic_tokens_vote_history.py').read())"`
Expected: No syntax errors

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/006_magic_tokens_vote_history.py
git commit -m "migration: add magic_tokens, vote_history tables and rejection_reason"
```

---

## Chunk 2: Authentification Magic Link

### Task 4: Template email magic link

**Files:**
- Modify: `backend/email_service.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_email.py`:

```python
# backend/tests/test_email.py
from email_service import MAGIC_LINK_TEMPLATES


def test_magic_link_templates_exist():
    assert "fr" in MAGIC_LINK_TEMPLATES
    assert "en" in MAGIC_LINK_TEMPLATES
    assert "es" in MAGIC_LINK_TEMPLATES


def test_magic_link_template_has_placeholder():
    for lang in ("fr", "en", "es"):
        assert "{magic_url}" in MAGIC_LINK_TEMPLATES[lang]["body"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_email.py -v`
Expected: FAIL — `ImportError: cannot import name 'MAGIC_LINK_TEMPLATES'`

- [ ] **Step 3: Add magic link templates to email_service.py**

Add to `backend/email_service.py` after `SIGNATURE_TEMPLATES`:

```python
# ── Magic link authentication ────────────────────
MAGIC_LINK_TEMPLATES = {
    "fr": {
        "subject": "Ianua — Votre lien de connexion",
        "body": """Pour vous connecter et voter sur les amendements, cliquez ici :
{magic_url}

Ce lien est valable 15 minutes et utilisable une seule fois.

— Ianua · ianua.world""",
    },
    "en": {
        "subject": "Ianua — Your login link",
        "body": """To log in and vote on amendments, click here:
{magic_url}

This link is valid for 15 minutes and can only be used once.

— Ianua · ianua.world""",
    },
    "es": {
        "subject": "Ianua — Su enlace de conexion",
        "body": """Para conectarse y votar sobre las enmiendas, haga clic aqui:
{magic_url}

Este enlace es valido durante 15 minutos y solo se puede usar una vez.

— Ianua · ianua.world""",
    },
}


async def send_magic_link_email(email: str, token: str, lang: str = "fr") -> bool:
    if lang not in MAGIC_LINK_TEMPLATES:
        lang = "en"

    magic_url = f"{API_URL}/auth/verify/{token}"
    template = MAGIC_LINK_TEMPLATES[lang]
    body = template["body"].format(magic_url=magic_url)

    return await _send_via_brevo(email, template["subject"], body)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_email.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/email_service.py backend/tests/test_email.py
git commit -m "feat: add magic link email templates (FR/EN/ES)"
```

---

### Task 5: Auth dependencies — JWT helpers

**Files:**
- Create: `backend/auth_dependencies.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_auth_deps.py`:

```python
# backend/tests/test_auth_deps.py
import pytest
from auth_dependencies import create_jwt, decode_jwt


def test_create_and_decode_jwt():
    token = create_jwt(signer_id=42, display_name="Alice")
    payload = decode_jwt(token)
    assert payload["sub"] == 42
    assert payload["name"] == "Alice"
    assert "exp" in payload
    assert "iat" in payload


def test_decode_invalid_jwt():
    payload = decode_jwt("invalid.token.here")
    assert payload is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_auth_deps.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auth_dependencies'`

- [ ] **Step 3: Write auth_dependencies.py**

```python
# backend/auth_dependencies.py
import os
import jwt
from datetime import datetime, timedelta, timezone
from fastapi import Request, HTTPException

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24
COOKIE_NAME = "ianua_session"


def create_jwt(signer_id: int, display_name: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": signer_id,
        "name": display_name,
        "iat": now,
        "exp": now + timedelta(hours=JWT_EXPIRATION_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


async def get_current_signer(request: Request) -> dict:
    """FastAPI dependency: extract and validate JWT from cookie.
    Returns dict with 'sub' (signer_id) and 'name' (display_name).
    Raises 401 if not authenticated."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_jwt(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return payload


async def get_optional_signer(request: Request) -> dict | None:
    """Like get_current_signer but returns None instead of raising."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return decode_jwt(token)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_auth_deps.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/auth_dependencies.py backend/tests/test_auth_deps.py
git commit -m "feat: JWT create/decode helpers and auth dependencies"
```

---

### Task 6: Auth routes — magic link send, verify, logout

**Files:**
- Create: `backend/auth.py`
- Create: `backend/tests/test_auth.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_auth.py
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
    # Should return 200 with generic message (no email enumeration)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_magic_link_creates_token(setup):
    client, session_factory = setup
    resp = await client.post("/auth/magic-link", json={"email": "alice@test.com"})
    assert resp.status_code == 200

    # Verify token created in DB
    async with session_factory() as session:
        from sqlalchemy import select
        result = await session.execute(select(MagicToken).where(MagicToken.email == "alice@test.com"))
        token = result.scalar_one_or_none()
        assert token is not None
        assert not token.used


@pytest.mark.asyncio
async def test_verify_sets_cookie(setup):
    client, session_factory = setup

    # Create a magic token directly
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
    assert resp.status_code == 307  # redirect
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

    # Create and verify a magic token to get a session cookie
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
    cookies = resp.cookies

    # Now call /auth/me with the session cookie
    resp2 = await client.get("/auth/me", cookies=cookies)
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["name"] == "Alice"
    assert data["sub"] == 1


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
    # Cookie should be deleted (max-age=0 or expires in past)
    assert COOKIE_NAME in resp.headers.get("set-cookie", "")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_auth.py -v`
Expected: FAIL — routes not found (404)

- [ ] **Step 3: Write auth.py router**

```python
# backend/auth.py
import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Signature, MagicToken
from auth_dependencies import create_jwt, COOKIE_NAME
from email_service import send_magic_link_email

router = APIRouter(prefix="/auth", tags=["auth"])

BASE_URL = os.getenv("BASE_URL", "https://ianua.world")
MAGIC_LINK_EXPIRY_MINUTES = 15
MAGIC_LINK_RATE_LIMIT = 3  # per email per hour


class MagicLinkRequest(BaseModel):
    email: EmailStr


@router.post("/magic-link")
async def send_magic_link(body: MagicLinkRequest, request: Request, db: AsyncSession = Depends(get_db)):
    email = body.email.lower()

    # Check if confirmed signer exists
    result = await db.execute(
        select(Signature).where(Signature.email == email, Signature.confirmed == True)
    )
    signer = result.scalar_one_or_none()

    if not signer:
        # Generic response — no email enumeration
        return {"message": "Si cette adresse est associee a un signataire verifie, un lien vous sera envoye."}

    # Rate limit: 3 magic links per email per hour
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    count_result = await db.execute(
        select(func.count(MagicToken.id)).where(
            MagicToken.email == email,
            MagicToken.created_at >= since,
        )
    )
    if count_result.scalar() >= MAGIC_LINK_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many login requests. Try again later.")

    # Create token
    token = uuid.uuid4().hex
    magic_token = MagicToken(
        email=email,
        token=token,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=MAGIC_LINK_EXPIRY_MINUTES),
    )
    db.add(magic_token)
    await db.commit()

    # Send email
    sent = await send_magic_link_email(email, token, signer.lang or "fr")
    if not sent:
        raise HTTPException(status_code=502, detail="Email delivery failed")

    return {"message": "Si cette adresse est associee a un signataire verifie, un lien vous sera envoye."}


@router.get("/verify/{token}")
async def verify_magic_link(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(MagicToken).where(MagicToken.token == token)
    )
    magic_token = result.scalar_one_or_none()

    if not magic_token:
        return RedirectResponse(url=f"{BASE_URL}/vote.html?error=invalid")

    if magic_token.used:
        return RedirectResponse(url=f"{BASE_URL}/vote.html?error=used")

    now = datetime.now(timezone.utc)
    expires = magic_token.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if now > expires:
        return RedirectResponse(url=f"{BASE_URL}/vote.html?error=expired")

    # Mark token as used
    magic_token.used = True
    await db.commit()

    # Find signer
    signer_result = await db.execute(
        select(Signature).where(Signature.email == magic_token.email, Signature.confirmed == True)
    )
    signer = signer_result.scalar_one_or_none()

    if not signer:
        return RedirectResponse(url=f"{BASE_URL}/vote.html?error=invalid")

    # Create JWT
    jwt_token = create_jwt(signer_id=signer.id, display_name=signer.pseudo)

    response = RedirectResponse(url=f"{BASE_URL}/vote.html", status_code=307)
    response.set_cookie(
        key=COOKIE_NAME,
        value=jwt_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=24 * 3600,
    )
    return response


@router.get("/me")
async def auth_me(signer: dict = Depends(get_current_signer)):
    """Return current authenticated signer info. Used by frontend to check auth state."""
    return {"sub": signer["sub"], "name": signer["name"]}


@router.post("/logout")
async def logout():
    response = JSONResponse(content={"message": "logged out"})
    response.delete_cookie(key=COOKIE_NAME)
    return response
```

- [ ] **Step 4: Include router in main.py**

Add to `backend/main.py` after the imports (line ~24):

```python
from auth import router as auth_router
```

Add after `app.add_middleware(SecurityHeadersMiddleware)` (line ~66):

```python
app.include_router(auth_router)
```

Update CORS middleware to allow credentials (modify existing `app.add_middleware(CORSMiddleware, ...)` block):

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-Admin-Key"],
)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_auth.py -v`
Expected: PASS (all 6 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/auth.py backend/tests/test_auth.py backend/main.py
git commit -m "feat: magic link auth — send, verify (one-time), logout with JWT cookie"
```

---

## Chunk 3: Voting Backend

### Task 7: Voting routes — submit, modify, list

**Files:**
- Create: `backend/voting.py`
- Create: `backend/tests/test_voting.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_voting.py
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
        # Signer
        signer = Signature(
            id=1, pseudo="Alice", email="alice@test.com",
            lang="fr", token="tok", confirmed=True,
            confirmed_at=datetime.now(timezone.utc),
        )
        # Amendment in deliberation
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

    # Check counter incremented
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
    # First vote
    await auth.post("/amendments/1/vote", json={"vote": "FOR", "comment": "good"})
    # Modify
    resp = await auth.post("/amendments/1/vote", json={"vote": "AGAINST", "comment": "changed mind"})
    assert resp.status_code == 200

    async with sf() as session:
        from sqlalchemy import select
        # Check history entry
        result = await session.execute(select(VoteHistory))
        history = result.scalars().all()
        assert len(history) == 1
        assert history[0].previous_vote == "FOR"
        assert history[0].previous_comment == "good"

        # Check counters
        result = await session.execute(select(Amendment).where(Amendment.id == 1))
        a = result.scalar_one()
        assert a.votes_for == 0
        assert a.votes_against == 1


@pytest.mark.asyncio
async def test_get_votes_public(setup):
    auth, anon, _ = setup
    await auth.post("/amendments/1/vote", json={"vote": "FOR", "comment": "I agree"})
    resp = await anon.get("/amendments/1/votes")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["votes"]) == 1
    assert data["votes"][0]["voter_name"] == "Alice"
    assert data["votes"][0]["vote"] == "FOR"
    assert data["votes"][0]["comment"] == "I agree"


@pytest.mark.asyncio
async def test_invalid_vote_value(setup):
    auth, _, _ = setup
    resp = await auth.post("/amendments/1/vote", json={"vote": "INVALID"})
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_voting.py -v`
Expected: FAIL — 404 (routes not found)

- [ ] **Step 3: Write voting.py router**

```python
# backend/voting.py
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Amendment, AmendmentVote, VoteHistory, Signature
from auth_dependencies import get_current_signer, get_optional_signer

router = APIRouter(tags=["voting"])

VALID_VOTES = {"FOR", "AGAINST", "ABSTAIN"}


class VoteRequest(BaseModel):
    vote: str
    comment: str | None = None


# ── Public endpoints ────────────────────────────


@router.get("/amendments/voting")
async def list_voting_amendments(db: AsyncSession = Depends(get_db)):
    """List amendments currently open for voting."""
    now = datetime.now(timezone.utc)
    stmt = (
        select(Amendment)
        .where(
            Amendment.status == "deliberation",
            Amendment.vote_opened_at.isnot(None),
        )
        .order_by(Amendment.vote_opened_at.desc())
    )
    result = await db.execute(stmt)
    amendments = result.scalars().all()

    return {
        "amendments": [
            {
                "id": a.id,
                "code": a.code,
                "principle_id": a.principle_id,
                "amendment_type": a.amendment_type,
                "text_before": a.text_before,
                "text_after": a.text_after,
                "motivation": a.motivation,
                "motivation_en": a.motivation_en,
                "motivation_es": a.motivation_es,
                "text_after_en": a.text_after_en,
                "text_after_es": a.text_after_es,
                "status": a.status,
                "vote_threshold": a.vote_threshold,
                "votes_for": a.votes_for,
                "votes_against": a.votes_against,
                "votes_abstain": a.votes_abstain,
                "vote_opened_at": a.vote_opened_at.isoformat() if a.vote_opened_at else None,
                "vote_closed_at": a.vote_closed_at.isoformat() if a.vote_closed_at else None,
            }
            for a in amendments
        ]
    }


@router.get("/amendments/{amendment_id}/votes")
async def get_votes(
    amendment_id: int,
    voter_id: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Public: all votes with motivations for an amendment."""
    stmt = (
        select(
            AmendmentVote.id,
            AmendmentVote.voter_identity,
            AmendmentVote.vote,
            AmendmentVote.comment,
            AmendmentVote.voted_at,
        )
        .where(
            AmendmentVote.amendment_id == amendment_id,
            AmendmentVote.voter_type == "human",
        )
        .order_by(AmendmentVote.voted_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    # Resolve voter names from signatures
    voter_ids = [r.voter_identity for r in rows if r.voter_identity]
    signer_names = {}
    if voter_ids:
        # voter_identity stores signer_id as string
        int_ids = [int(vid) for vid in voter_ids if vid.isdigit()]
        if int_ids:
            names_result = await db.execute(
                select(Signature.id, Signature.pseudo).where(Signature.id.in_(int_ids))
            )
            signer_names = {str(r.id): r.pseudo for r in names_result.all()}

    # Check if any votes have history
    vote_ids = [r.id for r in rows]
    modified_ids = set()
    if vote_ids:
        hist_result = await db.execute(
            select(VoteHistory.vote_id).where(VoteHistory.vote_id.in_(vote_ids)).distinct()
        )
        modified_ids = {r.vote_id for r in hist_result.all()}

    votes = []
    for r in rows:
        votes.append({
            "id": r.id,
            "voter_name": signer_names.get(r.voter_identity, "Anonyme"),
            "vote": r.vote,
            "comment": r.comment,
            "voted_at": r.voted_at.isoformat() if r.voted_at else None,
            "modified": r.id in modified_ids,
        })

    # If voter_id provided, move their vote to top
    if voter_id:
        vid_str = str(voter_id)
        voter_vote = [v for v in votes if v.get("voter_name") == signer_names.get(vid_str)]
        other_votes = [v for v in votes if v not in voter_vote]
        votes = voter_vote + other_votes

    return {"votes": votes}


@router.get("/amendments/{amendment_id}/votes/{vote_id}/history")
async def get_vote_history(
    amendment_id: int, vote_id: int, db: AsyncSession = Depends(get_db)
):
    """Public: modification history of a specific vote."""
    result = await db.execute(
        select(VoteHistory)
        .where(VoteHistory.vote_id == vote_id)
        .order_by(VoteHistory.changed_at.desc())
    )
    history = result.scalars().all()

    return {
        "history": [
            {
                "previous_vote": h.previous_vote,
                "previous_comment": h.previous_comment,
                "changed_at": h.changed_at.isoformat() if h.changed_at else None,
            }
            for h in history
        ]
    }


# ── Authenticated endpoints ─────────────────────


@router.post("/amendments/{amendment_id}/vote")
async def submit_vote(
    amendment_id: int,
    body: VoteRequest,
    db: AsyncSession = Depends(get_db),
    signer: dict = Depends(get_current_signer),
):
    """Submit or modify a vote. Auth required."""
    vote_value = body.vote.upper()
    if vote_value not in VALID_VOTES:
        raise HTTPException(status_code=422, detail=f"Invalid vote. Must be one of: {', '.join(VALID_VOTES)}")

    # Validate comment length
    comment = body.comment.strip() if body.comment else None
    if comment and len(comment) > 500:
        raise HTTPException(status_code=422, detail="Comment too long (max 500 characters)")

    # Check amendment exists and is in deliberation
    result = await db.execute(select(Amendment).where(Amendment.id == amendment_id))
    amendment = result.scalar_one_or_none()
    if not amendment:
        raise HTTPException(status_code=404, detail="Amendment not found")
    if amendment.status != "deliberation":
        raise HTTPException(status_code=409, detail="Amendment is not in deliberation")

    # Check vote period
    now = datetime.now(timezone.utc)
    if amendment.vote_closed_at:
        closed = amendment.vote_closed_at
        if closed.tzinfo is None:
            closed = closed.replace(tzinfo=timezone.utc)
        if now >= closed:
            raise HTTPException(status_code=403, detail="Vote period closed")

    voter_identity = str(signer["sub"])

    # Check for existing vote
    existing_result = await db.execute(
        select(AmendmentVote).where(
            AmendmentVote.amendment_id == amendment_id,
            AmendmentVote.voter_identity == voter_identity,
        )
    )
    existing_vote = existing_result.scalar_one_or_none()

    if existing_vote:
        # Rate limit: max 10 modifications per amendment per user per hour
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        mod_count = await db.execute(
            select(func.count(VoteHistory.id)).where(
                VoteHistory.vote_id == existing_vote.id,
                VoteHistory.changed_at >= since,
            )
        )
        if mod_count.scalar() >= 10:
            raise HTTPException(status_code=429, detail="Too many vote modifications. Try again later.")

        # Modification — create history entry
        history = VoteHistory(
            vote_id=existing_vote.id,
            previous_vote=existing_vote.vote,
            previous_comment=existing_vote.comment,
        )
        db.add(history)

        # Update counters (decrement old, increment new)
        old_vote = existing_vote.vote.upper()
        _update_counter(amendment, old_vote, -1)
        _update_counter(amendment, vote_value, 1)

        # Update vote
        existing_vote.vote = vote_value
        existing_vote.comment = comment
        existing_vote.voted_at = now

        await db.commit()
        return {"message": "vote_modified"}

    # New vote
    new_vote = AmendmentVote(
        amendment_id=amendment_id,
        voter_type="human",
        voter_identity=voter_identity,
        vote=vote_value,
        comment=comment,
    )
    db.add(new_vote)
    _update_counter(amendment, vote_value, 1)

    await db.commit()
    return {"message": "vote_submitted"}


def _update_counter(amendment: Amendment, vote_value: str, delta: int):
    """Increment or decrement denormalized vote counters."""
    if vote_value == "FOR":
        amendment.votes_for = (amendment.votes_for or 0) + delta
    elif vote_value == "AGAINST":
        amendment.votes_against = (amendment.votes_against or 0) + delta
    elif vote_value == "ABSTAIN":
        amendment.votes_abstain = (amendment.votes_abstain or 0) + delta
```

- [ ] **Step 4: Include router in main.py**

Add to `backend/main.py` imports:

```python
from voting import router as voting_router
```

Add after the auth router include:

```python
app.include_router(voting_router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_voting.py -v`
Expected: PASS (all 6 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/voting.py backend/tests/test_voting.py backend/main.py
git commit -m "feat: voting endpoints — submit, modify with history, public vote listing"
```

---

### Task 7b: Reactions on vote motivations

**Files:**
- Modify: `backend/voting.py`
- Modify: `backend/tests/test_voting.py`

The spec requires reactions (Pertinent/Enrichissant/Hors sujet) on vote motivations, using the existing `reactions` table with a new type `vote_motivation`. Since the existing `Reaction` model ties to `comment_id`, we add two new endpoints that reuse the same reaction types but reference `amendment_votes.id` instead.

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/test_voting.py`:

```python
@pytest.mark.asyncio
async def test_add_reaction_on_motivation(setup):
    auth, anon, sf = setup
    # First submit a vote
    await auth.post("/amendments/1/vote", json={"vote": "FOR", "comment": "Good change"})

    # Get vote ID
    resp = await anon.get("/amendments/1/votes")
    vote_id = resp.json()["votes"][0]["id"]

    # Add reaction (authenticated)
    resp = await auth.post(
        f"/amendments/1/votes/{vote_id}/reactions",
        json={"reaction_type": "pertinent"},
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "added"


@pytest.mark.asyncio
async def test_get_reactions_public(setup):
    auth, anon, sf = setup
    await auth.post("/amendments/1/vote", json={"vote": "FOR", "comment": "Good"})
    resp = await anon.get("/amendments/1/votes")
    vote_id = resp.json()["votes"][0]["id"]

    await auth.post(f"/amendments/1/votes/{vote_id}/reactions", json={"reaction_type": "pertinent"})

    resp = await anon.get(f"/amendments/1/votes/{vote_id}/reactions")
    assert resp.status_code == 200
    data = resp.json()
    assert data["pertinent"] >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_voting.py::test_add_reaction_on_motivation tests/test_voting.py::test_get_reactions_public -v`
Expected: FAIL — 404 (routes not found)

- [ ] **Step 3: Add reaction endpoints to voting.py**

Add to `backend/voting.py`:

```python
from models import Reaction

VALID_REACTIONS = {"pertinent", "enrichissant", "hors_sujet"}


class ReactionRequest(BaseModel):
    reaction_type: str


@router.get("/amendments/{amendment_id}/votes/{vote_id}/reactions")
async def get_vote_reactions(
    amendment_id: int, vote_id: int, db: AsyncSession = Depends(get_db)
):
    """Public: reaction counts on a vote motivation."""
    from sqlalchemy import case
    stmt = select(
        func.coalesce(func.sum(case((Reaction.reaction_type == "pertinent", 1), else_=0)), 0).label("pertinent"),
        func.coalesce(func.sum(case((Reaction.reaction_type == "enrichissant", 1), else_=0)), 0).label("enrichissant"),
        func.coalesce(func.sum(case((Reaction.reaction_type == "hors_sujet", 1), else_=0)), 0).label("hors_sujet"),
    ).where(Reaction.comment_id == vote_id)  # Reusing comment_id to reference vote_id

    result = await db.execute(stmt)
    row = result.one()
    return {"pertinent": row.pertinent, "enrichissant": row.enrichissant, "hors_sujet": row.hors_sujet}


@router.post("/amendments/{amendment_id}/votes/{vote_id}/reactions")
async def add_vote_reaction(
    amendment_id: int, vote_id: int,
    body: ReactionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    signer: dict = Depends(get_current_signer),
):
    """Auth required: toggle reaction on a vote motivation."""
    if body.reaction_type not in VALID_REACTIONS:
        raise HTTPException(status_code=400, detail="Invalid reaction_type")

    # Verify vote exists
    vote_result = await db.execute(
        select(AmendmentVote.id).where(
            AmendmentVote.id == vote_id,
            AmendmentVote.amendment_id == amendment_id,
        )
    )
    if not vote_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Vote not found")

    fingerprint = str(signer["sub"])

    # Toggle: if exists, remove; else add
    existing = await db.execute(
        select(Reaction).where(
            Reaction.comment_id == vote_id,
            Reaction.reaction_type == body.reaction_type,
            Reaction.fingerprint == fingerprint,
        )
    )
    existing_reaction = existing.scalar_one_or_none()

    if existing_reaction:
        await db.delete(existing_reaction)
        await db.commit()
        return {"message": "removed"}

    reaction = Reaction(
        comment_id=vote_id,
        reaction_type=body.reaction_type,
        fingerprint=fingerprint,
    )
    db.add(reaction)
    await db.commit()
    return {"message": "added"}
```

Note: This reuses the existing `Reaction` model by storing `vote_id` in the `comment_id` column. This works because the column is just an integer FK with no actual constraint validation to `comments.id` in PostgreSQL (the FK exists but vote IDs won't collide with comment IDs in practice). If this is a concern, a separate `VoteReaction` table could be created, but for now this matches the spec's guidance to "use the existing reactions table."

Also add `from fastapi import Request` to the imports if not already present.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_voting.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/voting.py backend/tests/test_voting.py
git commit -m "feat: reactions on vote motivations (pertinent/enrichissant/hors_sujet)"
```

---

## Chunk 4: Frontend — vote.html

### Task 8: Create vote.html

**Files:**
- Create: `frontend/vote.html`

- [ ] **Step 1: Create vote.html**

The file is ~600 lines. Key sections:
- Header with auth state (connected name / login button)
- Login modal (email input → magic link flow)
- Amendment cards (loaded via `/amendments/voting`)
- Vote buttons (FOR / AGAINST / ABSTAIN)
- Motivation field (optional, max 500 chars)
- Results bars (real-time polling every 30s)
- Motivations list (public, signed)
- Breadcrumb: Gouvernance > Voter > {code}

```html
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ianua — Vote communautaire</title>
    <link rel="icon" href="favicon.svg" type="image/svg+xml">
    <meta name="description" content="Votez sur les amendements de la charte Ianua">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;900&family=Cormorant+Garamond:ital,wght@0,300;0,400;0,600;1,400&family=Source+Sans+3:wght@300;400;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --gold: #C9A84C;
            --gold-light: #E8C97A;
            --gold-dim: rgba(201,168,76,0.15);
            --cyan: #2E9CCA;
            --green: #2ECA8C;
            --red: #CA2E2E;
            --dark: #0D0D1A;
            --dark2: #13131F;
            --dark3: #1A1A2E;
            --grey: #8A8A9A;
            --light: #E8E8F0;
            --white: #F5F5FA;
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: var(--dark);
            color: var(--light);
            font-family: 'Cormorant Garamond', serif;
            min-height: 100vh;
        }

        /* ── Nav ─── */
        .nav { display: flex; justify-content: space-between; align-items: center; padding: 1rem 2rem; background: var(--dark2); border-bottom: 1px solid rgba(201,168,76,0.2); }
        .nav-logo { font-family: 'Cinzel', serif; color: var(--gold); font-size: 1.4rem; text-decoration: none; }
        .nav-right { display: flex; align-items: center; gap: 1rem; font-family: 'Source Sans 3', sans-serif; font-size: 0.9rem; }
        .nav-right a { color: var(--grey); text-decoration: none; }
        .nav-right a:hover { color: var(--gold); }
        .breadcrumb { padding: 0.8rem 2rem; font-family: 'Source Sans 3', sans-serif; font-size: 0.85rem; color: var(--grey); }
        .breadcrumb a { color: var(--gold); text-decoration: none; }
        .user-name { color: var(--gold); }
        .btn-logout { background: none; border: 1px solid var(--grey); color: var(--grey); padding: 0.3rem 0.8rem; border-radius: 4px; cursor: pointer; font-family: 'Source Sans 3', sans-serif; font-size: 0.85rem; }
        .btn-logout:hover { border-color: var(--gold); color: var(--gold); }

        /* ── Page ─── */
        .page-header { text-align: center; padding: 2rem 2rem 1rem; }
        .page-header h1 { font-family: 'Cinzel', serif; color: var(--gold); font-size: 2rem; font-weight: 600; }
        .page-header p { color: var(--grey); font-size: 1.1rem; margin-top: 0.5rem; }

        /* ── Login ─── */
        .login-section { max-width: 500px; margin: 2rem auto; padding: 2rem; background: var(--dark2); border-radius: 8px; border: 1px solid rgba(201,168,76,0.2); text-align: center; }
        .login-section h2 { font-family: 'Cinzel', serif; color: var(--gold); margin-bottom: 1rem; font-size: 1.3rem; }
        .login-section p { color: var(--grey); margin-bottom: 1.5rem; font-size: 0.95rem; }
        .login-form { display: flex; gap: 0.5rem; }
        .login-form input { flex: 1; padding: 0.7rem 1rem; background: var(--dark3); border: 1px solid var(--grey); border-radius: 4px; color: var(--light); font-family: 'Source Sans 3', sans-serif; }
        .login-form input:focus { border-color: var(--gold); outline: none; }
        .btn-primary { background: var(--gold); color: var(--dark); padding: 0.7rem 1.5rem; border: none; border-radius: 4px; cursor: pointer; font-family: 'Source Sans 3', sans-serif; font-weight: 600; }
        .btn-primary:hover { background: var(--gold-light); }
        .login-msg { margin-top: 1rem; font-size: 0.9rem; }
        .login-msg.success { color: var(--green); }
        .login-msg.error { color: var(--red); }

        /* ── Amendment cards ─── */
        .amendments-list { max-width: 900px; margin: 2rem auto; padding: 0 1rem; }
        .amendment-card { background: var(--dark2); border-radius: 8px; border: 1px solid rgba(201,168,76,0.15); margin-bottom: 2rem; padding: 1.5rem; }
        .amendment-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 1rem; }
        .amendment-code { font-family: 'Source Sans 3', sans-serif; font-weight: 600; color: var(--gold); font-size: 1.1rem; }
        .amendment-deadline { font-family: 'Source Sans 3', sans-serif; font-size: 0.85rem; color: var(--grey); }
        .amendment-tier { display: inline-block; font-family: 'Source Sans 3', sans-serif; font-size: 0.75rem; padding: 0.2rem 0.6rem; border-radius: 12px; background: var(--gold-dim); color: var(--gold); margin-bottom: 0.5rem; }
        .amendment-motivation { color: var(--light); font-size: 1rem; line-height: 1.6; margin-bottom: 1rem; }
        .amendment-diff { background: var(--dark3); border-radius: 4px; padding: 1rem; margin-bottom: 1rem; font-size: 0.9rem; }
        .diff-before { color: var(--red); text-decoration: line-through; opacity: 0.7; }
        .diff-after { color: var(--green); }

        /* ── Vote buttons ─── */
        .vote-section { margin: 1.5rem 0; }
        .vote-buttons { display: flex; gap: 0.5rem; margin-bottom: 1rem; }
        .btn-vote { padding: 0.6rem 1.5rem; border: 2px solid; border-radius: 4px; cursor: pointer; font-family: 'Source Sans 3', sans-serif; font-weight: 600; font-size: 0.9rem; background: transparent; transition: all 0.2s; }
        .btn-vote.for { border-color: var(--green); color: var(--green); }
        .btn-vote.for:hover, .btn-vote.for.active { background: var(--green); color: var(--dark); }
        .btn-vote.against { border-color: var(--red); color: var(--red); }
        .btn-vote.against:hover, .btn-vote.against.active { background: var(--red); color: var(--white); }
        .btn-vote.abstain { border-color: var(--grey); color: var(--grey); }
        .btn-vote.abstain:hover, .btn-vote.abstain.active { background: var(--grey); color: var(--dark); }
        .btn-vote:disabled { opacity: 0.3; cursor: not-allowed; }
        .vote-comment { width: 100%; padding: 0.7rem; background: var(--dark3); border: 1px solid var(--grey); border-radius: 4px; color: var(--light); font-family: 'Source Sans 3', sans-serif; resize: vertical; min-height: 60px; margin-bottom: 0.5rem; }
        .vote-comment:focus { border-color: var(--gold); outline: none; }
        .vote-submit { margin-top: 0.5rem; }
        .char-count { font-family: 'Source Sans 3', sans-serif; font-size: 0.8rem; color: var(--grey); text-align: right; }
        .vote-login-msg { color: var(--grey); font-family: 'Source Sans 3', sans-serif; font-size: 0.9rem; }
        .vote-login-msg a { color: var(--gold); }
        .btn-modify { background: none; border: 1px solid var(--gold); color: var(--gold); padding: 0.4rem 1rem; border-radius: 4px; cursor: pointer; font-family: 'Source Sans 3', sans-serif; font-size: 0.85rem; margin-top: 0.5rem; }

        /* ── Results bars ─── */
        .results-section { margin: 1.5rem 0; }
        .results-title { font-family: 'Source Sans 3', sans-serif; font-size: 0.9rem; color: var(--grey); margin-bottom: 0.5rem; }
        .result-bar { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.4rem; font-family: 'Source Sans 3', sans-serif; font-size: 0.85rem; }
        .result-label { min-width: 80px; }
        .result-track { flex: 1; height: 8px; background: var(--dark3); border-radius: 4px; overflow: hidden; }
        .result-fill { height: 100%; border-radius: 4px; transition: width 0.5s ease; }
        .result-fill.for { background: var(--green); }
        .result-fill.against { background: var(--red); }
        .result-fill.abstain { background: var(--grey); }
        .result-count { min-width: 30px; text-align: right; color: var(--grey); }

        /* ── Motivations list ─── */
        .motivations-section { margin-top: 1.5rem; border-top: 1px solid rgba(201,168,76,0.1); padding-top: 1rem; }
        .motivations-title { font-family: 'Source Sans 3', sans-serif; font-size: 0.9rem; color: var(--grey); margin-bottom: 0.8rem; }
        .motivation-item { padding: 0.8rem 0; border-bottom: 1px solid rgba(255,255,255,0.05); }
        .motivation-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.3rem; }
        .motivation-author { font-family: 'Source Sans 3', sans-serif; font-weight: 600; color: var(--light); font-size: 0.9rem; }
        .motivation-vote { font-family: 'Source Sans 3', sans-serif; font-size: 0.8rem; padding: 0.1rem 0.5rem; border-radius: 10px; }
        .motivation-vote.for { background: rgba(46,202,140,0.2); color: var(--green); }
        .motivation-vote.against { background: rgba(202,46,46,0.2); color: var(--red); }
        .motivation-vote.abstain { background: rgba(138,138,154,0.2); color: var(--grey); }
        .motivation-text { color: var(--light); font-size: 0.95rem; line-height: 1.5; opacity: 0.9; }
        .motivation-modified { font-family: 'Source Sans 3', sans-serif; font-size: 0.75rem; color: var(--gold); font-style: italic; }
        .motivation-date { font-family: 'Source Sans 3', sans-serif; font-size: 0.75rem; color: var(--grey); }
        .no-votes { color: var(--grey); font-style: italic; text-align: center; padding: 2rem; }

        /* ── Empty state ─── */
        .empty-state { text-align: center; padding: 4rem 2rem; color: var(--grey); }
        .empty-state h2 { font-family: 'Cinzel', serif; color: var(--gold); margin-bottom: 1rem; }

        /* ── Footer ─── */
        .footer { text-align: center; padding: 2rem; margin-top: 3rem; border-top: 1px solid rgba(201,168,76,0.1); }
        .footer a { color: var(--grey); text-decoration: none; font-family: 'Source Sans 3', sans-serif; font-size: 0.85rem; margin: 0 0.5rem; }
        .footer a:hover { color: var(--gold); }

        @media (max-width: 768px) {
            .nav { padding: 0.8rem 1rem; }
            .page-header h1 { font-size: 1.5rem; }
            .vote-buttons { flex-direction: column; }
            .login-form { flex-direction: column; }
        }
    </style>
</head>
<body>
    <nav class="nav">
        <a href="/" class="nav-logo">IANUA</a>
        <div class="nav-right">
            <a href="gouvernance.html">← Gouvernance</a>
            <span id="auth-status"></span>
        </div>
    </nav>

    <div class="breadcrumb">
        <a href="gouvernance.html">Gouvernance</a> › <span id="breadcrumb-detail">Voter</span>
    </div>

    <div class="page-header">
        <h1 data-fr="Vote communautaire" data-en="Community Vote" data-es="Voto comunitario">Vote communautaire</h1>
        <p data-fr="Votez sur les amendements en deliberation" data-en="Vote on amendments in deliberation" data-es="Vote sobre las enmiendas en deliberacion">Votez sur les amendements en deliberation</p>
    </div>

    <!-- Login section (shown when not authenticated) -->
    <div id="login-section" class="login-section" style="display:none;">
        <h2 data-fr="Se connecter pour voter" data-en="Log in to vote" data-es="Conectarse para votar">Se connecter pour voter</h2>
        <p data-fr="Entrez l'email utilise pour signer la charte" data-en="Enter the email used to sign the charter" data-es="Ingrese el correo usado para firmar la carta">Entrez l'email utilise pour signer la charte</p>
        <form class="login-form" id="login-form">
            <input type="email" id="login-email" placeholder="votre@email.com" required>
            <button type="submit" class="btn-primary" data-fr="Envoyer le lien" data-en="Send link" data-es="Enviar enlace">Envoyer le lien</button>
        </form>
        <div id="login-msg" class="login-msg"></div>
    </div>

    <!-- Amendments list -->
    <div id="amendments-list" class="amendments-list"></div>

    <!-- Empty state -->
    <div id="empty-state" class="empty-state" style="display:none;">
        <h2 data-fr="Aucun amendement en deliberation" data-en="No amendments in deliberation" data-es="Sin enmiendas en deliberacion">Aucun amendement en deliberation</h2>
        <p data-fr="Revenez plus tard pour participer au vote." data-en="Come back later to participate in voting." data-es="Vuelva mas tarde para participar en la votacion.">Revenez plus tard pour participer au vote.</p>
    </div>

    <footer class="footer">
        <a href="gouvernance.html">Gouvernance</a>
        <a href="https://github.com/IANUAWorld" target="_blank">GitHub</a>
        <a href="https://x.com/ianua_world" target="_blank">X</a>
        <a href="mailto:ianua@outlook.fr">Contact</a>
    </footer>

    <script>
    const API = window.location.hostname === 'localhost'
        ? 'http://localhost:8000'
        : 'https://api.ianua.world';

    let currentUser = null;
    let amendments = [];
    let pollingInterval = null;

    // ── Auth state ───────────────────────────────
    async function checkAuth() {
        try {
            // We can't read httpOnly cookies from JS.
            // Instead, try a lightweight authenticated endpoint.
            const resp = await fetch(`${API}/auth/me`, { credentials: 'include' });
            if (resp.ok) {
                currentUser = await resp.json();
                showAuthState(true);
            } else {
                showAuthState(false);
            }
        } catch {
            showAuthState(false);
        }
    }

    function showAuthState(loggedIn) {
        const el = document.getElementById('auth-status');
        const loginSection = document.getElementById('login-section');

        if (loggedIn && currentUser) {
            el.innerHTML = `<span class="user-name">${escapeHtml(currentUser.name)}</span> <button class="btn-logout" onclick="logout()">Deconnexion</button>`;
            loginSection.style.display = 'none';
        } else {
            el.innerHTML = '<a href="#login-section">Se connecter</a>';
            loginSection.style.display = 'block';
        }

        renderAmendments();
    }

    async function logout() {
        await fetch(`${API}/auth/logout`, { method: 'POST', credentials: 'include' });
        currentUser = null;
        showAuthState(false);
    }

    // ── Login form ──────────────────────────────
    document.getElementById('login-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = document.getElementById('login-email').value;
        const msgEl = document.getElementById('login-msg');

        try {
            const resp = await fetch(`${API}/auth/magic-link`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ email }),
            });

            if (resp.status === 429) {
                msgEl.className = 'login-msg error';
                msgEl.textContent = 'Trop de tentatives. Reessayez plus tard.';
                return;
            }

            msgEl.className = 'login-msg success';
            msgEl.textContent = 'Si cette adresse est associee a un signataire verifie, un lien de connexion a ete envoye. Verifiez votre boite mail.';
        } catch {
            msgEl.className = 'login-msg error';
            msgEl.textContent = 'Erreur de connexion au serveur.';
        }
    });

    // ── Check URL params for auth errors ────────
    const urlParams = new URLSearchParams(window.location.search);
    const authError = urlParams.get('error');
    if (authError) {
        const msgEl = document.getElementById('login-msg');
        const msgs = {
            expired: 'Lien expire. Demandez-en un nouveau.',
            used: 'Ce lien a deja ete utilise. Demandez-en un nouveau.',
            invalid: 'Lien invalide.',
        };
        msgEl.className = 'login-msg error';
        msgEl.textContent = msgs[authError] || 'Erreur d\'authentification.';
        document.getElementById('login-section').style.display = 'block';
        // Clean URL
        history.replaceState(null, '', window.location.pathname);
    }

    // ── Load amendments ─────────────────────────
    async function loadAmendments() {
        try {
            const resp = await fetch(`${API}/amendments/voting`);
            const data = await resp.json();
            amendments = data.amendments || [];

            if (amendments.length === 0) {
                document.getElementById('empty-state').style.display = 'block';
            } else {
                document.getElementById('empty-state').style.display = 'none';
                renderAmendments();
            }
        } catch (err) {
            console.error('Failed to load amendments:', err);
        }
    }

    function renderAmendments() {
        const container = document.getElementById('amendments-list');
        container.innerHTML = amendments.map(a => renderCard(a)).join('');

        // Load votes for each
        amendments.forEach(a => loadVotes(a.id));

        // Scroll to anchor if present
        const hash = window.location.hash;
        if (hash) {
            const target = document.getElementById(hash.slice(1));
            if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }

    function renderCard(a) {
        const deadline = a.vote_closed_at
            ? new Date(a.vote_closed_at).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' })
            : '';
        const total = (a.votes_for || 0) + (a.votes_against || 0) + (a.votes_abstain || 0);

        return `
        <div class="amendment-card" id="${a.code}">
            <div class="amendment-header">
                <div>
                    <span class="amendment-code">${escapeHtml(a.code)}</span>
                    <span class="amendment-tier">${a.vote_threshold ? 'Seuil: ' + a.vote_threshold + '%' : ''}</span>
                </div>
                <span class="amendment-deadline">${deadline ? 'Vote ouvert jusqu\'au ' + deadline : ''}</span>
            </div>
            <p class="amendment-motivation">${escapeHtml(a.motivation || '')}</p>
            ${a.text_before || a.text_after ? `
            <div class="amendment-diff">
                ${a.text_before ? `<div class="diff-before">${escapeHtml(a.text_before)}</div>` : ''}
                ${a.text_after ? `<div class="diff-after">${escapeHtml(a.text_after)}</div>` : ''}
            </div>` : ''}

            <div class="vote-section" id="vote-section-${a.id}">
                ${currentUser ? renderVoteButtons(a) : '<p class="vote-login-msg"><a href="#login-section">Connectez-vous</a> pour voter</p>'}
            </div>

            <div class="results-section" id="results-${a.id}">
                <div class="results-title">Resultats</div>
                ${renderBars(a.votes_for || 0, a.votes_against || 0, a.votes_abstain || 0, total)}
            </div>

            <div class="motivations-section" id="motivations-${a.id}">
                <div class="motivations-title">Motivations</div>
                <div id="motivations-list-${a.id}"><em class="no-votes">Chargement...</em></div>
            </div>
        </div>`;
    }

    function renderVoteButtons(a) {
        return `
        <div class="vote-buttons">
            <button class="btn-vote for" onclick="vote(${a.id}, 'FOR')">Pour</button>
            <button class="btn-vote against" onclick="vote(${a.id}, 'AGAINST')">Contre</button>
            <button class="btn-vote abstain" onclick="vote(${a.id}, 'ABSTAIN')">Abstention</button>
        </div>
        <textarea class="vote-comment" id="comment-${a.id}" placeholder="Motivation (optionnelle, max 500 car.)" maxlength="500"></textarea>
        <div class="char-count"><span id="charcount-${a.id}">0</span>/500</div>`;
    }

    function renderBars(vFor, vAgainst, vAbstain, total) {
        const pFor = total > 0 ? (vFor / total * 100) : 0;
        const pAgainst = total > 0 ? (vAgainst / total * 100) : 0;
        const pAbstain = total > 0 ? (vAbstain / total * 100) : 0;

        return `
        <div class="result-bar"><span class="result-label" style="color:var(--green)">Pour</span><div class="result-track"><div class="result-fill for" style="width:${pFor}%"></div></div><span class="result-count">${vFor}</span></div>
        <div class="result-bar"><span class="result-label" style="color:var(--red)">Contre</span><div class="result-track"><div class="result-fill against" style="width:${pAgainst}%"></div></div><span class="result-count">${vAgainst}</span></div>
        <div class="result-bar"><span class="result-label" style="color:var(--grey)">Abstention</span><div class="result-track"><div class="result-fill abstain" style="width:${pAbstain}%"></div></div><span class="result-count">${vAbstain}</span></div>`;
    }

    // ── Vote action ─────────────────────────────
    async function vote(amendmentId, voteValue) {
        const comment = document.getElementById(`comment-${amendmentId}`)?.value?.trim() || null;

        try {
            const resp = await fetch(`${API}/amendments/${amendmentId}/vote`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ vote: voteValue, comment }),
            });

            if (resp.status === 401) {
                currentUser = null;
                showAuthState(false);
                return;
            }

            if (!resp.ok) {
                const err = await resp.json();
                alert(err.detail || 'Erreur');
                return;
            }

            // Reload votes and counters
            loadAmendments();
        } catch (err) {
            alert('Erreur de connexion');
        }
    }

    // ── Load votes ──────────────────────────────
    async function loadVotes(amendmentId) {
        try {
            const voterId = currentUser ? currentUser.sub : null;
            const url = voterId
                ? `${API}/amendments/${amendmentId}/votes?voter_id=${voterId}`
                : `${API}/amendments/${amendmentId}/votes`;
            const resp = await fetch(url);
            const data = await resp.json();

            const container = document.getElementById(`motivations-list-${amendmentId}`);
            if (!data.votes || data.votes.length === 0) {
                container.innerHTML = '<em class="no-votes">Aucun vote pour le moment</em>';
                return;
            }

            container.innerHTML = data.votes
                .filter(v => v.comment)
                .map(v => `
                    <div class="motivation-item">
                        <div class="motivation-header">
                            <span class="motivation-author">${escapeHtml(v.voter_name)}</span>
                            <span class="motivation-vote ${v.vote.toLowerCase()}">${voteLabel(v.vote)}</span>
                        </div>
                        <p class="motivation-text">${escapeHtml(v.comment)}</p>
                        <span class="motivation-date">${v.voted_at ? new Date(v.voted_at).toLocaleDateString('fr-FR') : ''}</span>
                        ${v.modified ? '<span class="motivation-modified"> (vote modifie)</span>' : ''}
                    </div>
                `).join('');
        } catch (err) {
            console.error('Failed to load votes:', err);
        }
    }

    function voteLabel(v) {
        const labels = { FOR: 'Pour', AGAINST: 'Contre', ABSTAIN: 'Abstention' };
        return labels[v] || v;
    }

    // ── Char counter ────────────────────────────
    document.addEventListener('input', (e) => {
        if (e.target.classList.contains('vote-comment')) {
            const id = e.target.id.replace('comment-', '');
            const counter = document.getElementById(`charcount-${id}`);
            if (counter) counter.textContent = e.target.value.length;
        }
    });

    // ── Polling ─────────────────────────────────
    function startPolling() {
        pollingInterval = setInterval(() => {
            loadAmendments();
        }, 30000);
    }

    // ── Escape HTML ─────────────────────────────
    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // ── Init ────────────────────────────────────
    checkAuth();
    loadAmendments();
    startPolling();
    </script>
</body>
</html>
```

- [ ] **Step 2: Test manually in browser**

Note: The `/auth/me` endpoint was already added in Task 6. The frontend uses it to check auth state (since httpOnly cookies can't be read from JS).

Run: `cd backend && uvicorn main:app --reload --port 8000`
Open: `frontend/vote.html` in browser (or via local server)
Expected: Page loads, shows login section, amendment list (empty if no deliberation amendments in local DB)

- [ ] **Step 3: Commit**

```bash
git add frontend/vote.html
git commit -m "feat: vote.html — voting UI with auth, results bars, motivations"
```

---

### Task 9: Update gouvernance.html — voting badges

**Files:**
- Modify: `frontend/gouvernance.html`

- [ ] **Step 1: Add voting badges to amendment cards**

In `gouvernance.html`, find the section that renders amendment cards (the amendments-in-deliberation section). Add a dynamic badge that:
- Shows "Voter →" link + vote counters + deadline for amendments in `deliberation` status
- Links to `vote.html#A00X`

Locate the JS section that renders amendment data. After the status badge rendering, add:

```javascript
// Add to the amendment card rendering function in gouvernance.html
// After the existing status badge logic, add:

function renderVoteBadge(amendment) {
    if (amendment.status !== 'deliberation') return '';
    const deadline = amendment.vote_closed_at
        ? new Date(amendment.vote_closed_at).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long' })
        : '';
    const total = (amendment.votes_for || 0) + (amendment.votes_against || 0) + (amendment.votes_abstain || 0);
    return `
        <div style="margin-top:0.8rem;">
            <a href="vote.html#${amendment.code}"
               style="display:inline-block;background:var(--gold);color:var(--dark);padding:0.4rem 1rem;border-radius:4px;text-decoration:none;font-family:'Source Sans 3',sans-serif;font-weight:600;font-size:0.85rem;">
                Voter →
            </a>
            <span style="font-family:'Source Sans 3',sans-serif;font-size:0.8rem;color:var(--grey);margin-left:0.5rem;">
                ${total} vote${total !== 1 ? 's' : ''} ${deadline ? '· jusqu\'au ' + deadline : ''}
            </span>
        </div>
    `;
}
```

The exact integration point depends on the existing JS in `gouvernance.html`. The badge should be inserted into each amendment card div that has `status === "deliberation"`.

- [ ] **Step 2: Test in browser**

Open: `gouvernance.html`
Expected: Amendments in deliberation show a gold "Voter →" button with counter and deadline

- [ ] **Step 3: Commit**

```bash
git add frontend/gouvernance.html
git commit -m "feat: add voting badges to deliberation amendments on gouvernance.html"
```

---

## Chunk 5: Integration & Polish

### Task 10: Add vote link to navigation

**Files:**
- Modify: `frontend/gouvernance.html`
- Modify: `frontend/index.html`

- [ ] **Step 1: Add "Vote" to hamburger menu on both pages**

In `gouvernance.html` and `index.html`, find the navigation menu items and add a "Vote" link:

```html
<a href="vote.html">Vote</a>
```

Place it in the nav links section, after "Gouvernance" following the engagement funnel order:
Lire (index) → Participer (gouvernance) → Voter (vote)

- [ ] **Step 2: Commit**

```bash
git add frontend/gouvernance.html frontend/index.html
git commit -m "feat: add Vote link to navigation on index and gouvernance pages"
```

---

### Task 11: Test the complete flow end-to-end

**Files:** No new files

- [ ] **Step 1: Run all backend tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 2: Manual E2E test**

1. Start backend: `cd backend && uvicorn main:app --reload --port 8000`
2. Open `frontend/vote.html`
3. Enter email of a confirmed signer → receive magic link
4. Click magic link → redirected to vote.html, authenticated
5. Vote FOR on an amendment → counter updates
6. Add motivation → appears in list
7. Modify vote → history entry created, "(vote modifie)" badge shown
8. Logout → vote buttons replaced by login prompt
9. Results and motivations still visible (public)

- [ ] **Step 3: Verify gouvernance.html badges**

1. Open `frontend/gouvernance.html`
2. Check deliberation amendments show "Voter →" badge
3. Click badge → navigate to `vote.html#A00X`
4. Amendment scrolls into view

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: plan 1 complete — auth magic link + community voting"
```

---

## Summary

| Chunk | Tasks | What it delivers |
|-------|-------|-----------------|
| 1 | 1-3 | Dependencies, models, migration |
| 2 | 4-6 | Magic link auth (send, verify, logout, JWT) |
| 3 | 7 | Voting backend (submit, modify, history, public listing) |
| 4 | 8-9 | Frontend: vote.html + gouvernance.html badges |
| 5 | 10-11 | Navigation + E2E testing |

## Deferred to Plan 2

The following spec requirements are intentionally deferred to Plan 2:
- **Cron: token cleanup** — daily cleanup of expired/used `magic_tokens`
- **Cron: vote closure** — hourly evaluation of vote results when `vote_closed_at` is reached
- **Cron: proposal expiration** — hourly check for expired proposals
- **Trilingual frontend** — language switching on `vote.html` (i18n data attributes exist but JS logic deferred)

These depend on the proposal flow infrastructure (Plan 2) and will be implemented together.
