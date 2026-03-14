import asyncio
import pytest
import pytest_asyncio
from sqlalchemy import event, Text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database import Base
from models import (
    Subscriber, Comment, Reaction, Amendment, AmendmentVote,
    Signature, MagicToken, VoteHistory
)

# Patch ARRAY columns to Text for SQLite compatibility in tests
from sqlalchemy import ARRAY
for col in Amendment.__table__.columns:
    if isinstance(col.type, ARRAY):
        col.type = Text()


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
