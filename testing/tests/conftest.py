"""Shared fixtures for testing environment tests."""

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.models.database import Base, Usuario
import app.models.database as database_module
import app.services.finance as finance_module
import app.services.onboarding as onboarding_module
import app.services.reminder as reminder_module


@pytest.fixture()
def in_memory_db(monkeypatch):
    """In-memory SQLite DB with all tables created. Monkeypatches SessionLocal."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(finance_module, "SessionLocal", testing_session)
    monkeypatch.setattr(onboarding_module, "SessionLocal", testing_session)
    monkeypatch.setattr(database_module, "SessionLocal", testing_session)
    monkeypatch.setattr(reminder_module, "SessionLocal", testing_session)

    session = testing_session()
    try:
        yield {"session": session, "SessionLocal": testing_session}
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def test_user(in_memory_db):
    """Creates a test user in the in-memory DB."""
    import uuid
    session = in_memory_db["session"]
    user = Usuario(
        nombre="Test User",
        email=f"{uuid.uuid4()}@example.com",
        whatsapp_id="5491112345678",
    )
    session.add(user)
    session.commit()
    return {"user": user, "session": session, "SessionLocal": in_memory_db["SessionLocal"]}
