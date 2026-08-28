from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.finance as finance_module
from app.models.database import Base, MovimientoFinanciero, Usuario
from app.services.dispatcher import _register_multiop
from app.services.llm import LLMService
from app.services.llm_contract import resolve_relative_date


@pytest.fixture()
def db_context(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(finance_module, "SessionLocal", testing_session_local)

    session = testing_session_local()
    try:
        yield {"session": session, "session_factory": testing_session_local}
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _create_user(session, whatsapp_id="5491111111111"):
    user = Usuario(
        nombre="Test User",
        email=f"user_{whatsapp_id}@example.com",
        whatsapp_id=whatsapp_id,
    )
    session.add(user)
    session.commit()
    return user


TODAY = date(2026, 8, 21)  # viernes


def test_iso_passthrough():
    assert resolve_relative_date("2026-08-19", TODAY) == date(2026, 8, 19)


def test_yesterday():
    assert resolve_relative_date("ayer", TODAY) == date(2026, 8, 20)


def test_last_weekday_resolves_backward():
    assert resolve_relative_date("martes", TODAY) == date(2026, 8, 18)


def test_invalid_or_missing_returns_today():
    assert resolve_relative_date(None, TODAY) == TODAY
    assert resolve_relative_date("no-fecha", TODAY) == TODAY
    assert resolve_relative_date("2026-13-99", TODAY) == TODAY


def test_future_beyond_tolerance_returns_today():
    assert resolve_relative_date("2027-01-01", TODAY) == TODAY


@pytest.mark.asyncio
async def test_process_message_normalizes_fecha():
    from tests.test_llm import _process_message_with_mock_response

    result = await _process_message_with_mock_response({
        "intent": "expense", "movement_type": "egreso", "amount": 100,
        "fecha": "ayer", "reply_text": "",
    })
    assert result["movements"][0]["fecha"] == str(date.today() - timedelta(days=1))  # noqa: DTZ011


@pytest.mark.asyncio
async def test_context_is_appended_to_system_prompt():
    with patch.object(LLMService, "_get_provider") as gp:
        provider = AsyncMock()
        provider.generate_json.return_value = {"intent": "greeting"}
        gp.return_value = provider
        await LLMService.process_message("hola", context="FECHA ACTUAL: 2026-08-21.")
    sent_prompt = provider.generate_json.await_args.kwargs.get("system_prompt")
    assert "FECHA ACTUAL: 2026-08-21." in sent_prompt


@pytest.mark.asyncio
async def test_gaste_100_ayer_persists_yesterday(db_context):
    session = db_context["session"]
    _create_user(session)

    extracted_data = {
        "intent": "expense",
        "movements": [
            {
                "movement_type": "egreso",
                "amount": 100,
                "currency": "ARS",
                "description": "gasté 100 ayer",
                "fecha": "ayer",
                "reply_text": "",
            }
        ],
    }
    movements = extracted_data["movements"]

    await _register_multiop(
        "5491111111111", "w1", "gasté 100 ayer", extracted_data, movements
    )

    movement = session.query(MovimientoFinanciero).first()
    assert movement is not None
    assert movement.fecha_movimiento == date.today() - timedelta(days=1)  # noqa: DTZ011
