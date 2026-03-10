from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey, UniqueConstraint
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


# ── Phase 2 — Gouvernance (structure seulement, pas d'endpoint en v1) ──

class Amendment(Base):
    __tablename__ = "amendments"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    type = Column(String(20), nullable=False)        # 'clause' | 'principle' | 'redline'
    principle_id = Column(String(5), nullable=True)   # 'I'...'VIII' ou NULL si clause globale
    content = Column(Text, nullable=False)
    status = Column(String(20), default="open")       # 'open' | 'adopted' | 'rejected'
    threshold = Column(Integer, nullable=False)        # 66 ou 80
    opens_at = Column(DateTime, nullable=False)
    closes_at = Column(DateTime, nullable=False)       # durée : 60 jours
    created_at = Column(DateTime, server_default=func.now())


class Vote(Base):
    __tablename__ = "votes"

    id = Column(Integer, primary_key=True, index=True)
    amendment_id = Column(Integer, ForeignKey("amendments.id", ondelete="CASCADE"), nullable=False)
    vote_type = Column(String(20), nullable=False)    # 'adopt' | 'amend' | 'reject' | 'abstain'
    fingerprint = Column(String(64), nullable=False)
    lang = Column(String(5), default="fr")
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("amendment_id", "fingerprint", name="uq_vote_per_fingerprint"),
    )
