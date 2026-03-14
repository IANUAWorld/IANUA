from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey, UniqueConstraint,
    ARRAY
)
from sqlalchemy.sql import func
from database import Base


class Subscriber(Base):
    __tablename__ = "subscribers"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    lang = Column(String(5), default="fr")
    token = Column(String(64), unique=True)
    confirmed = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    confirmed_at = Column(DateTime, nullable=True)


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)
    principle_id = Column(String(5), nullable=False, index=True)
    author_name = Column(String(100), nullable=False)
    author_country = Column(String(100), nullable=True)
    content = Column(Text, nullable=False)
    lang = Column(String(5), default="fr")
    status = Column(String(20), default="pending", index=True)
    fingerprint = Column(String(64), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    approved_at = Column(DateTime, nullable=True)


class Reaction(Base):
    __tablename__ = "reactions"

    id = Column(Integer, primary_key=True, index=True)
    comment_id = Column(Integer, ForeignKey("comments.id", ondelete="CASCADE"), nullable=False)
    reaction_type = Column(String(20), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("comment_id", "reaction_type", "fingerprint", name="uq_reaction_per_fingerprint"),
    )


# ── Gouvernance — Registre des amendements (pérenne) ─────────────────

class Amendment(Base):
    __tablename__ = "amendments"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(10), unique=True, nullable=False, index=True)  # "A001", "A001-R"

    # Cible
    principle_id = Column(String(20), nullable=True)                     # semantic id, NULL si global
    target = Column(String(20), nullable=False)                          # principle_body / redline / global
    amendment_type = Column(String(20), nullable=False)                  # addition / modification / suppression / new_redline

    # Contenu
    text_before = Column(Text, nullable=True)
    text_after = Column(Text, nullable=True)
    motivation = Column(Text, nullable=False)
    inspiration = Column(Text, nullable=True)

    # Voie de proposition
    source_type = Column(String(20), nullable=False)                     # founder / community / ia_audit
    proposed_by = Column(String(100), nullable=True)
    supporting_comments = Column(ARRAY(Integer), nullable=True)
    supporting_models = Column(ARRAY(Text), nullable=True)

    # Gouvernance
    phase = Column(String(10), nullable=False)                           # phase_1 / phase_2 / phase_3
    status = Column(String(20), nullable=False, default="draft")         # draft / deliberation / accepted / ratified / rejected
    ratified_by = Column(String(100), nullable=True)
    ratified_at = Column(DateTime, nullable=True)
    rejected_reason = Column(Text, nullable=True)

    # Votes (Phase 2+)
    votes_for = Column(Integer, default=0)
    votes_against = Column(Integer, default=0)
    votes_abstain = Column(Integer, default=0)
    vote_threshold = Column(Integer, nullable=True)
    vote_opened_at = Column(DateTime, nullable=True)
    vote_closed_at = Column(DateTime, nullable=True)

    # Traçabilité
    proposed_at = Column(DateTime, server_default=func.now())
    published_at = Column(DateTime, nullable=True)
    github_commit = Column(String(100), nullable=True)
    charte_version = Column(String(10), nullable=True)

    # Internationalisation
    motivation_en = Column(Text, nullable=True)
    motivation_es = Column(Text, nullable=True)
    text_after_en = Column(Text, nullable=True)
    text_after_es = Column(Text, nullable=True)

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


# ── Signatures — Soutien global à la démarche ────────────────────────

class Signature(Base):
    __tablename__ = "signatures"

    id = Column(Integer, primary_key=True, index=True)
    pseudo = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    lang = Column(String(5), default="fr")
    token = Column(String(64), unique=True)
    confirmed = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    confirmed_at = Column(DateTime, nullable=True)


class AmendmentVote(Base):
    __tablename__ = "amendment_votes"

    id = Column(Integer, primary_key=True, index=True)
    amendment_id = Column(Integer, ForeignKey("amendments.id", ondelete="CASCADE"), nullable=False)
    voter_type = Column(String(10), nullable=False)      # human / ia
    voter_identity = Column(String(100), nullable=True)   # OAuth id ou ia_audit_id
    voter_model = Column(String(100), nullable=True)      # si ia : nom du modèle
    vote = Column(String(10), nullable=False)             # for / against / abstain
    comment = Column(Text, nullable=True)
    voted_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("amendment_id", "voter_identity", name="uq_amendment_vote_per_voter"),
    )


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
    audit_response_id = Column(Integer, nullable=True)
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
