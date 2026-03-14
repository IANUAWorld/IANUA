# Plan 2 — Flux de proposition, Audit IA & Navigation globale

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre aux signataires de proposer des amendements (brouillons → proposition → soutiens → deliberation), lancer des audits IA multi-modeles, et unifier la navigation Phase 2 avec transparence totale.

**Architecture:** Migration Alembic 007 pour 7 nouvelles tables + colonnes sur `amendments`. Nouveaux modules backend : `backend/proposals.py` (brouillons, soutiens, retrait), `backend/governance.py` (contestations, signalements, admin actions, transparence), `backend/audit_ia.py` (audit multi-modeles), `backend/crons.py` (expiration, cloture, nettoyage). Nouvelles pages : `frontend/proposer.html`, `frontend/transparence.html`. Modifications : `gouvernance.html` (registre enrichi), navigation globale.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic + Brevo + vanilla JS + httpx (appels API IA)

**Specs:** `docs/superpowers/specs/2026-03-14-amendment-proposal-flow-design.md`

**Depends on:** Plan 1 (auth magic link + voting) — completed and merged.

---

## Architecture Decisions (review resolutions)

### AD1 — Route conflict resolution: `/amendments/{code}` vs `/proposals/drafts`

The existing `main.py` has `GET /amendments/{code}` which would catch `/proposals/drafts` as `code="drafts"`. Resolution: **all new proposal routes use prefix `/proposals`** instead of `/amendments`. This avoids conflicts entirely:
- `GET /proposals/drafts` (not `/proposals/drafts`)
- `POST /proposals/drafts` (create)
- `GET /proposals/public` (not `/proposals/public`)
- `POST /proposals/{id}/support` (not `/amendments/{id}/support`)
- `POST /proposals/{id}/withdraw`

The existing `/amendments/*` routes in `main.py` and `voting.py` remain untouched. The `proposals.py` router uses `prefix="/proposals"`.

### AD2 — `rejected_reason` vs `rejection_reason`

The existing model has `rejected_reason` (Text, nullable) at line 80 of `models.py`. The spec calls it `rejection_reason`. We **reuse the existing `rejected_reason` column** — no migration needed. Same resolution as Plan 1.

### AD3 — Resource identifiers: `id` (int) vs `code` (string)

Existing routes use `code` (string like "A003"). New proposal routes use integer `id` internally. Resolution: **new routes use `{id}` (integer PK)** consistently. The `code` field remains for display. The `/amendments/{code}` route in main.py stays as-is for backward compatibility. New frontend pages use `id` for API calls and `code` for display/anchors.

### AD4 — ForeignKey constraints on `signer_id`, `challenger_id`, `reporter_id`

The spec says "FK → signataires confirmés". We **add proper ForeignKey constraints** to `signatures.id` on all signer reference columns. This matches the spec and ensures referential integrity.

### AD5 — Existing serialization in main.py

The existing `GET /amendments` and `GET /amendments/{code}` endpoints in `main.py` do NOT need to expose new fields (`title`, `tier`, `author_id`). The enriched `gouvernance.html` will call the **new** `GET /proposals/public` endpoint which returns all fields. The old endpoints remain backward-compatible for Phase 1 data.

### AD6 — `principle_id` single vs multiple

The spec says "Select multiple" for principles concerned. The existing `Amendment.principle_id` is a single `String(20)`. We **keep single `principle_id`** as a practical simplification — most amendments target one principle. "transversal" is used when multiple are affected. This is documented as a deliberate design decision.

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `backend/proposals.py` | Routes brouillons (CRUD, share, submit) + soutiens + retrait + endpoint principes charte. Prefix: `/proposals` (see AD1) |
| `backend/governance.py` | Routes contestation palier + signalements + admin actions (delete, dismiss, requalify) + transparence |
| `backend/audit_ia.py` | Routes audit IA (trigger, publish, reject, listing public/admin) |
| `backend/crons.py` | Endpoints cron : expiration propositions, cloture votes, nettoyage tokens |
| `backend/tests/test_proposals.py` | Tests brouillons, soutiens, retrait, soumission |
| `backend/tests/test_governance.py` | Tests contestation, signalements, admin actions |
| `backend/tests/test_audit_ia.py` | Tests audit IA trigger, publish, reject |
| `backend/tests/test_crons.py` | Tests crons expiration, cloture, nettoyage |
| `backend/alembic/versions/007_proposal_flow_tables.py` | Migration : 7 nouvelles tables + colonnes amendments |
| `frontend/proposer.html` | Page proposition : brouillons, formulaire, suivi |
| `frontend/transparence.html` | Log public des actions admin |

### Modified Files

| File | Changes |
|------|---------|
| `backend/main.py` | Include 4 nouveaux routers |
| `backend/models.py` | 7 nouveaux modeles + colonnes Amendment |
| `backend/email_service.py` | Templates notification (tier requalification, suppression pour abus) |
| `backend/requirements.txt` | Ajouter `anthropic`, `openai`, `google-generativeai`, `mistralai` |
| `frontend/gouvernance.html` | Registre enrichi avec tous statuts + badge "Proposer" + lien Transparence |
| `frontend/index.html` | Lien "Proposer" dans nav + etat connexion global |
| `frontend/vote.html` | Section "Voix IA" repliable sous chaque amendement + etat connexion global |

---

## Chunk 1: Migration & Models

### Task 1: Add all new SQLAlchemy models

**Files:**
- Modify: `backend/models.py`
- Modify: `backend/tests/conftest.py`
- Create: `backend/tests/test_proposal_models.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_proposal_models.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import (
    DraftShareToken, DraftComment, AmendmentSupport,
    TierChallenge, ContentReport, AdminAction, AuditResponse
)


def test_all_new_models_exist():
    assert DraftShareToken.__tablename__ == "draft_share_tokens"
    assert DraftComment.__tablename__ == "draft_comments"
    assert AmendmentSupport.__tablename__ == "amendment_supports"
    assert TierChallenge.__tablename__ == "tier_challenges"
    assert ContentReport.__tablename__ == "content_reports"
    assert AdminAction.__tablename__ == "admin_actions"
    assert AuditResponse.__tablename__ == "audit_responses"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_proposal_models.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Add models to models.py**

Add after `VoteHistory` class:

```python
class DraftShareToken(Base):
    __tablename__ = "draft_share_tokens"

    id = Column(Integer, primary_key=True, index=True)
    amendment_id = Column(Integer, ForeignKey("amendments.id", ondelete="CASCADE"), nullable=False)
    token = Column(String(64), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now())


class DraftComment(Base):
    __tablename__ = "draft_comments"

    id = Column(Integer, primary_key=True, index=True)
    amendment_id = Column(Integer, ForeignKey("amendments.id", ondelete="CASCADE"), nullable=False)
    author_name = Column(String(100), nullable=False)
    comment = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class AmendmentSupport(Base):
    __tablename__ = "amendment_supports"

    id = Column(Integer, primary_key=True, index=True)
    amendment_id = Column(Integer, ForeignKey("amendments.id", ondelete="CASCADE"), nullable=False, index=True)
    signer_id = Column(Integer, ForeignKey("signatures.id"), nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("amendment_id", "signer_id", name="uq_support_per_signer"),
    )


class TierChallenge(Base):
    __tablename__ = "tier_challenges"

    id = Column(Integer, primary_key=True, index=True)
    amendment_id = Column(Integer, ForeignKey("amendments.id", ondelete="CASCADE"), nullable=False, index=True)
    challenger_id = Column(Integer, ForeignKey("signatures.id"), nullable=False)
    suggested_tier = Column(String(20), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("amendment_id", "challenger_id", name="uq_challenge_per_signer"),
    )


class ContentReport(Base):
    __tablename__ = "content_reports"

    id = Column(Integer, primary_key=True, index=True)
    amendment_id = Column(Integer, ForeignKey("amendments.id", ondelete="CASCADE"), nullable=False)
    reporter_id = Column(Integer, ForeignKey("signatures.id"), nullable=False)
    category = Column(String(30), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("amendment_id", "reporter_id", name="uq_report_per_signer"),
    )


class AdminAction(Base):
    __tablename__ = "admin_actions"

    id = Column(Integer, primary_key=True, index=True)
    amendment_id = Column(Integer, ForeignKey("amendments.id", ondelete="CASCADE"), nullable=False)
    action = Column(String(30), nullable=False)
    reason = Column(Text, nullable=False)
    via = Column(String(20), nullable=False)
    audit_response_id = Column(Integer, ForeignKey("audit_responses.id"), nullable=True)
    acted_at = Column(DateTime, server_default=func.now())


class AuditResponse(Base):
    __tablename__ = "audit_responses"

    id = Column(Integer, primary_key=True, index=True)
    amendment_id = Column(Integer, ForeignKey("amendments.id", ondelete="CASCADE"), nullable=False, index=True)
    model_name = Column(String(50), nullable=False)
    model_version = Column(String(50), nullable=True)
    prompt_used = Column(Text, nullable=False)
    response_text = Column(Text, nullable=False)
    published = Column(Boolean, default=False)
    publication_decision_logged = Column(Boolean, default=False)
    audited_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("amendment_id", "model_name", name="uq_audit_per_model"),
    )
```

Also add new columns to `Amendment` model (after existing columns, before closing of class):

```python
    # Phase 2 — Proposal flow
    author_id = Column(Integer, nullable=True)
    title = Column(String(120), nullable=True)
    tier = Column(String(20), nullable=True)  # mineur / substantiel / fondateur
    expires_at = Column(DateTime, nullable=True)
    suggested_position = Column(Integer, nullable=True)
    submission_language = Column(String(2), nullable=True)
    deletion_justification = Column(Text, nullable=True)
    withdrawn_at = Column(DateTime, nullable=True)
    deliberation_duration_days = Column(Integer, nullable=True)
    tier_requalified = Column(Boolean, default=False)
    tier_requalified_by = Column(String(20), nullable=True)
    tier_requalified_at = Column(DateTime, nullable=True)
    tier_original = Column(String(20), nullable=True)
```

Update `conftest.py` imports to include new models and patch any new ARRAY columns if needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_proposal_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/models.py backend/tests/
git commit -m "feat: add 7 new models for proposal flow, governance, and audit IA"
```

---

### Task 2: Write Alembic migration 007

**Files:**
- Create: `backend/alembic/versions/007_proposal_flow_tables.py`

- [ ] **Step 1: Write migration**

```python
"""Add proposal flow tables and amendment columns.

Revision ID: 007
Revises: 006
"""
from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade():
    # draft_share_tokens
    op.create_table(
        "draft_share_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("amendment_id", sa.Integer(), sa.ForeignKey("amendments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(64), unique=True, nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # draft_comments
    op.create_table(
        "draft_comments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("amendment_id", sa.Integer(), sa.ForeignKey("amendments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_name", sa.String(100), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # amendment_supports
    op.create_table(
        "amendment_supports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("amendment_id", sa.Integer(), sa.ForeignKey("amendments.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("signer_id", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("amendment_id", "signer_id", name="uq_support_per_signer"),
    )

    # tier_challenges
    op.create_table(
        "tier_challenges",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("amendment_id", sa.Integer(), sa.ForeignKey("amendments.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("challenger_id", sa.Integer(), nullable=False),
        sa.Column("suggested_tier", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("amendment_id", "challenger_id", name="uq_challenge_per_signer"),
    )

    # content_reports
    op.create_table(
        "content_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("amendment_id", sa.Integer(), sa.ForeignKey("amendments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reporter_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("amendment_id", "reporter_id", name="uq_report_per_signer"),
    )

    # admin_actions
    op.create_table(
        "admin_actions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("amendment_id", sa.Integer(), sa.ForeignKey("amendments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("via", sa.String(20), nullable=False),
        sa.Column("audit_response_id", sa.Integer(), nullable=True),
        sa.Column("acted_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # audit_responses
    op.create_table(
        "audit_responses",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("amendment_id", sa.Integer(), sa.ForeignKey("amendments.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("model_name", sa.String(50), nullable=False),
        sa.Column("model_version", sa.String(50), nullable=True),
        sa.Column("prompt_used", sa.Text(), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=False),
        sa.Column("published", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("publication_decision_logged", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("audited_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("amendment_id", "model_name", name="uq_audit_per_model"),
    )

    # Add columns to amendments
    op.add_column("amendments", sa.Column("author_id", sa.Integer(), nullable=True))
    op.add_column("amendments", sa.Column("title", sa.String(120), nullable=True))
    op.add_column("amendments", sa.Column("tier", sa.String(20), nullable=True))
    op.add_column("amendments", sa.Column("expires_at", sa.DateTime(), nullable=True))
    op.add_column("amendments", sa.Column("suggested_position", sa.Integer(), nullable=True))
    op.add_column("amendments", sa.Column("submission_language", sa.String(2), nullable=True))
    op.add_column("amendments", sa.Column("deletion_justification", sa.Text(), nullable=True))
    op.add_column("amendments", sa.Column("withdrawn_at", sa.DateTime(), nullable=True))
    op.add_column("amendments", sa.Column("deliberation_duration_days", sa.Integer(), nullable=True))
    op.add_column("amendments", sa.Column("tier_requalified", sa.Boolean(), server_default=sa.text("false")))
    op.add_column("amendments", sa.Column("tier_requalified_by", sa.String(20), nullable=True))
    op.add_column("amendments", sa.Column("tier_requalified_at", sa.DateTime(), nullable=True))
    op.add_column("amendments", sa.Column("tier_original", sa.String(20), nullable=True))


def downgrade():
    cols = [
        "author_id", "title", "tier", "expires_at", "suggested_position",
        "submission_language", "deletion_justification", "withdrawn_at",
        "deliberation_duration_days", "tier_requalified", "tier_requalified_by",
        "tier_requalified_at", "tier_original",
    ]
    for col in cols:
        op.drop_column("amendments", col)

    op.drop_table("audit_responses")
    op.drop_table("admin_actions")
    op.drop_table("content_reports")
    op.drop_table("tier_challenges")
    op.drop_table("amendment_supports")
    op.drop_table("draft_comments")
    op.drop_table("draft_share_tokens")
```

- [ ] **Step 2: Verify syntax**

Run: `cd backend && python3 -c "import ast; ast.parse(open('alembic/versions/007_proposal_flow_tables.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/007_proposal_flow_tables.py
git commit -m "migration: add 7 tables for proposal flow, governance, audit IA + amendment columns"
```

---

## Chunk 2: Proposal Lifecycle Backend

### Task 3: Charter principles endpoint + email templates

**Files:**
- Modify: `backend/email_service.py`

- [ ] **Step 1: Add notification email templates**

Add to `backend/email_service.py` — templates for tier requalification notification and abuse deletion notification:

```python
TIER_REQUALIFIED_TEMPLATES = {
    "fr": {
        "subject": "Ianua — Palier de votre proposition requalifie",
        "body": """Votre proposition [{code}] "{title}" a ete requalifiee.

Ancien palier : {old_tier}
Nouveau palier : {new_tier}
Raison : {reason}

Consultez la gouvernance : {base_url}/gouvernance

— Ianua · ianua.world""",
    },
    "en": {
        "subject": "Ianua — Your proposal tier was requalified",
        "body": """Your proposal [{code}] "{title}" has been requalified.

Previous tier: {old_tier}
New tier: {new_tier}
Reason: {reason}

View governance: {base_url}/gouvernance

— Ianua · ianua.world""",
    },
    "es": {
        "subject": "Ianua — Nivel de su propuesta reclasificado",
        "body": """Su propuesta [{code}] "{title}" ha sido reclasificada.

Nivel anterior: {old_tier}
Nuevo nivel: {new_tier}
Razon: {reason}

Ver gobernanza: {base_url}/gouvernance

— Ianua · ianua.world""",
    },
}

ABUSE_DELETION_TEMPLATES = {
    "fr": {
        "subject": "Ianua — Votre proposition a ete supprimee",
        "body": """Votre proposition [{code}] "{title}" a ete supprimee pour le motif suivant :

{reason}

Voie : {via}

Le log de cette action est consultable publiquement sur :
{base_url}/transparence

— Ianua · ianua.world""",
    },
    "en": {
        "subject": "Ianua — Your proposal has been removed",
        "body": """Your proposal [{code}] "{title}" has been removed for the following reason:

{reason}

Via: {via}

The log of this action is publicly available at:
{base_url}/transparence

— Ianua · ianua.world""",
    },
    "es": {
        "subject": "Ianua — Su propuesta ha sido eliminada",
        "body": """Su propuesta [{code}] "{title}" ha sido eliminada por el siguiente motivo:

{reason}

Via: {via}

El registro de esta accion esta disponible publicamente en:
{base_url}/transparence

— Ianua · ianua.world""",
    },
}

BASE_URL_FOR_TEMPLATES = os.getenv("BASE_URL", "https://ianua.world")


async def send_tier_requalified_email(email: str, code: str, title: str, old_tier: str, new_tier: str, reason: str, lang: str = "fr") -> bool:
    if lang not in TIER_REQUALIFIED_TEMPLATES:
        lang = "en"
    template = TIER_REQUALIFIED_TEMPLATES[lang]
    body = template["body"].format(code=code, title=title, old_tier=old_tier, new_tier=new_tier, reason=reason, base_url=BASE_URL_FOR_TEMPLATES)
    return await _send_via_brevo(email, template["subject"], body)


async def send_abuse_deletion_email(email: str, code: str, title: str, reason: str, via: str, lang: str = "fr") -> bool:
    if lang not in ABUSE_DELETION_TEMPLATES:
        lang = "en"
    template = ABUSE_DELETION_TEMPLATES[lang]
    body = template["body"].format(code=code, title=title, reason=reason, via=via, base_url=BASE_URL_FOR_TEMPLATES)
    return await _send_via_brevo(email, template["subject"], body)
```

- [ ] **Step 2: Commit**

```bash
git add backend/email_service.py
git commit -m "feat: add email templates for tier requalification and abuse deletion notifications"
```

---

### Task 4: Proposals router — drafts CRUD, share, submit, support, withdraw

**Files:**
- Create: `backend/proposals.py`
- Create: `backend/tests/test_proposals.py`

This is the largest task. The router handles:
- `GET /amendments/drafts` — list user's drafts
- `POST /amendments/drafts` — create draft (max 5)
- `PUT /amendments/drafts/{id}` — update draft
- `DELETE /amendments/drafts/{id}` — delete draft
- `POST /amendments/drafts/{id}/submit` — submit draft → proposed (text frozen)
- `POST /amendments/drafts/{id}/share` — generate share token
- `GET /proposals/shared/{token}` — read shared draft (no auth)
- `POST /proposals/shared/{token}/comments` — add private comment (no auth, rate limited)
- `GET /proposals/public` — list all non-draft amendments (with filters)
- `GET /amendments/{id}/supports` — list supports (public)
- `POST /amendments/{id}/support` — support a proposal (auth)
- `POST /amendments/{id}/withdraw` — withdraw own proposal (auth)
- `GET /charter/principles` — list charter principles for form prefill

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_proposals.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

from database import Base, get_db
from models import Signature, Amendment, AmendmentSupport, DraftShareToken
from auth_dependencies import create_jwt, COOKIE_NAME


@pytest_asyncio.fixture
async def setup():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with sf() as session:
        s1 = Signature(id=1, pseudo="Alice", email="alice@test.com", lang="fr", token="t1", confirmed=True, confirmed_at=datetime.now(timezone.utc))
        s2 = Signature(id=2, pseudo="Bob", email="bob@test.com", lang="en", token="t2", confirmed=True, confirmed_at=datetime.now(timezone.utc))
        session.add_all([s1, s2])
        await session.commit()

    from main import app
    async def override_db():
        async with sf() as session:
            yield session
    app.dependency_overrides[get_db] = override_db

    jwt_alice = create_jwt(signer_id=1, display_name="Alice")
    jwt_bob = create_jwt(signer_id=2, display_name="Bob")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test", cookies={COOKIE_NAME: jwt_alice}) as alice:
        async with AsyncClient(transport=transport, base_url="http://test", cookies={COOKIE_NAME: jwt_bob}) as bob:
            async with AsyncClient(transport=transport, base_url="http://test") as anon:
                yield alice, bob, anon, sf

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_draft(setup):
    alice, _, _, _ = setup
    resp = await alice.post("/amendments/drafts", json={
        "amendment_type": "modification",
        "title": "Clarify transparency",
        "principle_id": "transparence",
        "text_after": "New transparency text",
        "motivation": "Needs clarity",
        "tier": "mineur",
        "submission_language": "fr",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] is not None
    assert data["status"] == "draft"


@pytest.mark.asyncio
async def test_list_drafts(setup):
    alice, _, _, _ = setup
    await alice.post("/amendments/drafts", json={
        "amendment_type": "modification", "title": "Draft 1",
        "principle_id": "transparence", "text_after": "text",
        "motivation": "reason", "tier": "mineur", "submission_language": "fr",
    })
    resp = await alice.get("/amendments/drafts")
    assert resp.status_code == 200
    assert len(resp.json()["drafts"]) >= 1


@pytest.mark.asyncio
async def test_max_5_drafts(setup):
    alice, _, _, _ = setup
    for i in range(5):
        await alice.post("/amendments/drafts", json={
            "amendment_type": "modification", "title": f"Draft {i}",
            "principle_id": "transparence", "text_after": "text",
            "motivation": "reason", "tier": "mineur", "submission_language": "fr",
        })
    resp = await alice.post("/amendments/drafts", json={
        "amendment_type": "modification", "title": "Draft 6",
        "principle_id": "transparence", "text_after": "text",
        "motivation": "reason", "tier": "mineur", "submission_language": "fr",
    })
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_submit_draft(setup):
    alice, _, _, sf = setup
    resp = await alice.post("/amendments/drafts", json={
        "amendment_type": "modification", "title": "Submit test",
        "principle_id": "transparence", "text_after": "new text",
        "motivation": "improve", "tier": "mineur", "submission_language": "fr",
    })
    draft_id = resp.json()["id"]

    resp = await alice.post(f"/amendments/drafts/{draft_id}/submit")
    assert resp.status_code == 200

    async with sf() as session:
        result = await session.execute(select(Amendment).where(Amendment.id == draft_id))
        a = result.scalar_one()
        assert a.status == "proposed"
        assert a.expires_at is not None


@pytest.mark.asyncio
async def test_addition_forces_fondateur(setup):
    alice, _, _, sf = setup
    resp = await alice.post("/amendments/drafts", json={
        "amendment_type": "addition", "title": "New principle",
        "text_after": "A new principle text",
        "motivation": "needed", "tier": "mineur", "submission_language": "fr",
        "suggested_position": 4,
    })
    draft_id = resp.json()["id"]
    await alice.post(f"/amendments/drafts/{draft_id}/submit")

    async with sf() as session:
        result = await session.execute(select(Amendment).where(Amendment.id == draft_id))
        a = result.scalar_one()
        assert a.tier == "fondateur"


@pytest.mark.asyncio
async def test_support_proposal(setup):
    alice, bob, _, sf = setup
    # Alice creates and submits
    resp = await alice.post("/amendments/drafts", json={
        "amendment_type": "modification", "title": "Support test",
        "principle_id": "transparence", "text_after": "text",
        "motivation": "reason", "tier": "mineur", "submission_language": "fr",
    })
    draft_id = resp.json()["id"]
    await alice.post(f"/amendments/drafts/{draft_id}/submit")

    # Bob supports
    resp = await bob.post(f"/amendments/{draft_id}/support", json={"comment": "Great idea"})
    assert resp.status_code == 200

    # Alice cannot support her own
    resp = await alice.post(f"/amendments/{draft_id}/support", json={})
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_withdraw_proposal(setup):
    alice, _, _, sf = setup
    resp = await alice.post("/amendments/drafts", json={
        "amendment_type": "modification", "title": "Withdraw test",
        "principle_id": "transparence", "text_after": "text",
        "motivation": "reason", "tier": "mineur", "submission_language": "fr",
    })
    draft_id = resp.json()["id"]
    await alice.post(f"/amendments/drafts/{draft_id}/submit")

    resp = await alice.post(f"/amendments/{draft_id}/withdraw")
    assert resp.status_code == 200

    async with sf() as session:
        result = await session.execute(select(Amendment).where(Amendment.id == draft_id))
        a = result.scalar_one()
        assert a.status == "withdrawn"


@pytest.mark.asyncio
async def test_share_draft(setup):
    alice, _, anon, _ = setup
    resp = await alice.post("/amendments/drafts", json={
        "amendment_type": "modification", "title": "Share test",
        "principle_id": "transparence", "text_after": "text",
        "motivation": "reason", "tier": "mineur", "submission_language": "fr",
    })
    draft_id = resp.json()["id"]

    # Generate share link
    resp = await alice.post(f"/amendments/drafts/{draft_id}/share")
    assert resp.status_code == 200
    token = resp.json()["token"]

    # Anon can read via token
    resp = await anon.get(f"/proposals/shared/{token}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Share test"


@pytest.mark.asyncio
async def test_public_amendments_list(setup):
    alice, _, anon, _ = setup
    resp = await alice.post("/amendments/drafts", json={
        "amendment_type": "modification", "title": "Public test",
        "principle_id": "transparence", "text_after": "text",
        "motivation": "reason", "tier": "mineur", "submission_language": "fr",
    })
    draft_id = resp.json()["id"]
    await alice.post(f"/amendments/drafts/{draft_id}/submit")

    resp = await anon.get("/proposals/public?status=proposed")
    assert resp.status_code == 200
    assert len(resp.json()["amendments"]) >= 1


@pytest.mark.asyncio
async def test_charter_principles(setup):
    _, _, anon, _ = setup
    resp = await anon.get("/charter/principles")
    assert resp.status_code == 200
    data = resp.json()
    assert "principles" in data
    assert len(data["principles"]) == 8
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_proposals.py -v`
Expected: FAIL — 404 routes not found

- [ ] **Step 3: Write proposals.py**

The implementation should follow the spec exactly. Key logic:
- Draft creation: auto-generate `code` (e.g., `P001`, `P002`, ...) based on max existing code
- Submit: freeze text, set `proposed_at`, calculate `expires_at` based on tier/palier
- Force `tier = fondateur` for addition/deletion types
- Support: check not author, check not already supported, check status == proposed
- Withdraw: check author, check status == proposed
- Charter principles: return hardcoded list of 8 principle IDs with display names (from `VALID_PRINCIPLES` in main.py)

Code length: ~350 lines. Write complete implementation.

- [ ] **Step 4: Include router in main.py**

```python
from proposals import router as proposals_router
# ...
app.include_router(proposals_router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python3 -m pytest tests/test_proposals.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/proposals.py backend/tests/test_proposals.py backend/main.py
git commit -m "feat: proposal lifecycle — drafts CRUD, share, submit, support, withdraw"
```

---

## Chunk 3: Governance Backend

### Task 5: Governance router — tier challenges, reports, admin actions, transparency

**Files:**
- Create: `backend/governance.py`
- Create: `backend/tests/test_governance.py`

Endpoints:
- `POST /amendments/{id}/challenge-tier` — contest tier (auth, signer only)
- `GET /amendments/{id}/challenges` — list challenges (public)
- `POST /amendments/{id}/report` — report for abuse (auth)
- `POST /admin/amendments/{id}/delete` — admin delete (admin only)
- `POST /admin/amendments/{id}/dismiss-reports` — dismiss reports (admin only)
- `POST /admin/amendments/{id}/requalify-tier` — requalify tier (admin only)
- `GET /transparency/actions` — public log of admin actions

- [ ] **Step 1: Write failing tests**

Tests should cover:
- Challenge tier: only upward, unique per signer, convergence auto-requalification at 3
- Report: unique per signer, 3 reports → notification
- Admin delete with reason logged
- Admin dismiss reports with reason
- Transparency endpoint returns all actions publicly

~120 lines of tests.

- [ ] **Step 2: Run tests (fail)**

- [ ] **Step 3: Write governance.py**

~250 lines. Key logic:
- Tier challenge convergence: when 3rd challenge arrives, check if all 3 suggest same tier → auto requalify + log AdminAction + notify author
- Admin verify via `verify_admin` dependency (from main.py)
- All admin actions logged to `admin_actions` table
- Transparency endpoint is public, returns all admin actions sorted by date desc

- [ ] **Step 4: Include router in main.py**

- [ ] **Step 5: Run tests (pass)**

- [ ] **Step 6: Commit**

```bash
git add backend/governance.py backend/tests/test_governance.py backend/main.py
git commit -m "feat: governance — tier challenges, reports, admin actions, transparency log"
```

---

## Chunk 4: Audit IA Backend

### Task 6: Audit IA router

**Files:**
- Create: `backend/audit_ia.py`
- Create: `backend/tests/test_audit_ia.py`
- Modify: `backend/requirements.txt`

Endpoints:
- `POST /admin/amendments/{id}/audit` — trigger audit (admin)
- `POST /admin/amendments/{id}/audit/{audit_id}/publish` — publish response (admin)
- `POST /admin/amendments/{id}/audit/{audit_id}/reject` — reject response (admin)
- `GET /amendments/{id}/audit-responses` — public published responses
- `GET /admin/amendments/{id}/audit-responses` — admin all responses

- [ ] **Step 1: Add AI provider dependencies**

Add to `requirements.txt`:

```
anthropic==0.39.0
openai==1.52.0
```

Note: Only add Anthropic and OpenAI for now. Other providers (Google, Mistral, xAI, Meta) will be added when their APIs are configured. The router should have a provider registry pattern that makes adding new providers trivial.

- [ ] **Step 2: Write failing tests**

Tests should cover:
- Trigger audit creates audit_responses rows (mock the actual API calls)
- Publish marks published=true + logs AdminAction
- Reject marks publication_decision_logged=true + logs AdminAction
- Public endpoint only returns published responses
- Admin endpoint returns all responses
- Unique constraint: can't audit same model twice on same amendment

~100 lines of tests. Mock the AI API calls since we can't call real APIs in tests.

- [ ] **Step 3: Write audit_ia.py**

~200 lines. Key design:
- Provider registry dict mapping model names to async callables
- Each provider function calls the respective API and returns `(response_text, model_version)`
- Error handling: if API call fails, skip that model and report error to admin
- Sequential execution (not parallel) as spec requires

```python
AI_PROVIDERS = {
    "claude": call_anthropic,
    "gpt-4o": call_openai,
    # More providers added as configured
}
```

- [ ] **Step 4: Include router in main.py**

- [ ] **Step 5: Run tests (pass)**

- [ ] **Step 6: Commit**

```bash
git add backend/audit_ia.py backend/tests/test_audit_ia.py backend/main.py backend/requirements.txt
git commit -m "feat: audit IA — multi-model trigger, publish/reject, provider registry"
```

---

## Chunk 5: Crons

### Task 7: Cron endpoints

**Files:**
- Create: `backend/crons.py`
- Create: `backend/tests/test_crons.py`

Three cron endpoints (called by Railway cron scheduler or external scheduler):
- `POST /crons/expire-proposals` — expire proposals past deadline
- `POST /crons/close-votes` — close votes and compute results
- `POST /crons/cleanup-tokens` — delete used/expired magic tokens

All protected by admin key.

- [ ] **Step 1: Write failing tests**

```python
# Tests should verify:
# - Expired proposal transitions to 'expired' status
# - Vote closure computes FOR/(FOR+AGAINST), checks quorum for fondateur
# - Sets rejected_reason='quorum_not_met' when quorum not met
# - Token cleanup removes used and expired tokens
```

~80 lines of tests.

- [ ] **Step 2: Write crons.py**

~150 lines. Key logic:
- `expire_proposals`: `UPDATE amendments SET status='expired' WHERE status='proposed' AND expires_at <= now()`
- `close_votes`: for each amendment where `vote_closed_at <= now() AND status='deliberation'`:
  - Count total votes, check quorum (for fondateur: 30% of confirmed signatories)
  - Calculate `FOR / (FOR + AGAINST)`, compare to threshold
  - Set status to `ratified` or `rejected` (with `rejected_reason` if quorum not met)
- `cleanup_tokens`: `DELETE FROM magic_tokens WHERE used=true OR expires_at < now()`

- [ ] **Step 3: Include router in main.py**

- [ ] **Step 4: Run tests (pass)**

- [ ] **Step 5: Commit**

```bash
git add backend/crons.py backend/tests/test_crons.py backend/main.py
git commit -m "feat: cron endpoints — expire proposals, close votes, cleanup tokens"
```

---

## Chunk 6: Frontend — proposer.html

### Task 8: Create proposer.html

**Files:**
- Create: `frontend/proposer.html`

~700 lines. Sections:
1. **Nav + breadcrumb** (Gouvernance > Proposer)
2. **Auth gate** — if not connected, show login form (magic link), redirect after auth
3. **Mes brouillons** — list of drafts with edit/preview/share/delete/submit actions
4. **Nouveau brouillon** — form with dynamic fields based on amendment type:
   - Modification: principle selector + text prérempli (readonly) + text proposé + motivation + tier
   - Ajout: text proposé + position + motivation + tier (forced fondateur)
   - Suppression: principle selector + justification + motivation + tier (forced fondateur)
5. **Mes propositions soumises** — tracking: support count, challenges, status
6. **Diff preview** — client-side visual diff of text_before vs text_after

Style: same design system as vote.html and gouvernance.html.

- [ ] **Step 1: Create the file**

Write complete HTML/CSS/JS following the design system (Cinzel/Cormorant/Source Sans 3, gold/cyan/dark palette).

Key JS functions:
- `loadDrafts()` — fetch `/proposals/drafts`, render cards
- `loadProposals()` — fetch `/proposals/public?author_id={me}`, render tracking
- `loadPrinciples()` — fetch `/charter/principles`, populate form selectors
- `createDraft(formData)` — POST to `/proposals/drafts`
- `submitDraft(id)` — POST to `/amendments/drafts/{id}/submit`
- `shareDraft(id)` — POST to `/amendments/drafts/{id}/share`, show link
- `deleteDraft(id)` — DELETE `/amendments/drafts/{id}`
- `renderDiffPreview(before, after)` — simple word-level diff highlighting

- [ ] **Step 2: Test in browser**

- [ ] **Step 3: Commit**

```bash
git add frontend/proposer.html
git commit -m "feat: proposer.html — amendment proposal form, drafts management, diff preview"
```

---

## Chunk 7: Frontend — transparence.html, gouvernance enrichment, global navigation

### Task 9: Create transparence.html

**Files:**
- Create: `frontend/transparence.html`

~200 lines. Simple page:
- Nav + breadcrumb (Gouvernance > Transparence)
- Title: "Transparence — Log des actions admin"
- Table/list fetched from `/transparency/actions`
- Each entry: date, amendment code, action type, reason, via
- Same design system

- [ ] **Step 1: Create the file**
- [ ] **Step 2: Commit**

```bash
git add frontend/transparence.html
git commit -m "feat: transparence.html — public admin actions log"
```

---

### Task 10: Enrich gouvernance.html with all statuts

**Files:**
- Modify: `frontend/gouvernance.html`

Currently the registre loads from a static JSON file. For Phase 2, it needs to also load from the API (`/proposals/public`) to show community-proposed amendments with their dynamic statuts.

Changes:
- Add fetch from `/proposals/public` for community proposals
- Add badges for: proposed (+ support count + deadline), withdrawn, expired, deleted
- Add "Proposer un amendement →" button at top of registry
- Add "Transparence" link in footer
- Add "Soutenir →" badge on proposed amendments (links to `proposer.html#P00X` or direct action if connected)
- Add "Voix IA" collapsible section under each amendment with audits (fetch `/amendments/{id}/audit-responses`, display in cyan)

- [ ] **Step 1: Modify gouvernance.html**
- [ ] **Step 2: Test in browser**
- [ ] **Step 3: Commit**

```bash
git add frontend/gouvernance.html
git commit -m "feat: enriched gouvernance.html — all statuts, propose button, IA voices, transparency link"
```

---

### Task 11: Global navigation + auth state

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/vote.html`
- Modify: `frontend/gouvernance.html`

Add to all pages:
- Auth state check via `/auth/me` (if JWT cookie present)
- Display signed-in name + logout button in nav header
- Add "Proposer" link in navigation (engagement funnel: Lire → Participer → Proposer → Voter)
- Breadcrumb on action pages

This is mainly JS snippet injection into existing pages — a shared `auth-state.js` pattern or inline on each page.

- [ ] **Step 1: Add auth state to all pages**
- [ ] **Step 2: Test navigation flow across all pages**
- [ ] **Step 3: Commit**

```bash
git add frontend/
git commit -m "feat: global auth state, navigation funnel, breadcrumbs across all pages"
```

---

### Task 12: Add Voix IA section to vote.html

**Files:**
- Modify: `frontend/vote.html`

Add collapsible "Voix IA" section under each amendment card:
- Fetch `/amendments/{id}/audit-responses`
- Display published responses in cyan cards
- Each card: model name + version + date
- Prompt shown as header (shared across all models)
- Collapsed by default, expandable on click
- Note: "Les voix IA eclairent la deliberation mais ne participent pas au vote"

- [ ] **Step 1: Add IA voices section**
- [ ] **Step 2: Commit**

```bash
git add frontend/vote.html
git commit -m "feat: voix IA section on vote.html — collapsible, cyan, per-amendment"
```

---

## Chunk 8: Final Integration

### Task 13: Run all tests

- [ ] **Step 1: Run full test suite**

Run: `cd backend && python3 -m pytest tests/ -v`
Expected: All tests pass (22 existing + ~40 new ≈ 60+ tests)

- [ ] **Step 2: Verify no import errors**

Run: `cd backend && python3 -c "from main import app; print('App loads OK')"`

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "chore: plan 2 complete — proposal flow, audit IA, navigation globale"
```

---

## Summary

| Chunk | Tasks | What it delivers |
|-------|-------|-----------------|
| 1 | 1-2 | 7 new models, 13 new Amendment columns, migration 007 |
| 2 | 3-4 | Email templates, proposal lifecycle (drafts, submit, support, withdraw, charter principles) |
| 3 | 5 | Governance (tier challenges, reports, admin actions, transparency) |
| 4 | 6 | Audit IA multi-model (trigger, publish/reject, provider registry) |
| 5 | 7 | Crons (expire proposals, close votes, cleanup tokens) |
| 6 | 8 | proposer.html frontend |
| 7 | 9-12 | transparence.html, gouvernance enrichment, global navigation, Voix IA section |
| 8 | 13 | Final integration testing |

## Deferred

- AI provider integrations beyond Claude/GPT-4o (Gemini, Mistral, Grok, Llama) — add when API keys configured
- Trilingual frontend i18n switching on new pages — data attributes in place, switching logic deferred
- Email notifications for community events (new proposals, vote results) — Phase 2 ultérieure
