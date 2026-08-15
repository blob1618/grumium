"""Tests del dispatcher para límites de gasto por categoría (STK-46)."""

from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.services.conversation import LastCreatedLimit, PendingLimit, PendingLimitDelete
from app.services.dispatcher import process_incoming_message
from app.services.limit import LimitResult
from app.services.onboarding import OnboardingDecision, OnboardingResult


def known_user():
    return OnboardingResult(OnboardingDecision.KNOWN_USER)


def create_limit_llm(**overrides):
    result = {
        "intent": "create_limit",
        "limit_category": "Ropa",
        "limit_amount": 300000,
        "limit_month": None,
        "limit_year": None,
        "reply_text": "LLM dice",
    }
    result.update(overrides)
    return result


@contextmanager
def limit_flow_patches(**overrides):
    defaults = dict(
        onboarding=known_user(),
        llm=create_limit_llm(),
        awaiting_rename=False,
        awaiting_reminder=False,
        awaiting_limit_year=False,
        awaiting_limit_data=False,
        awaiting_limit_delete_category=False,
        awaiting_limit_month=False,
    )
    defaults.update(overrides)

    with (
        patch(
            "app.services.dispatcher.OnboardingService.prepare_whatsapp_message",
            return_value=defaults["onboarding"],
        ),
        patch(
            "app.services.dispatcher.ConversationService.is_awaiting_rename",
            new_callable=AsyncMock,
            return_value=defaults["awaiting_rename"],
        ),
        patch(
            "app.services.dispatcher.ConversationService.is_awaiting_reminder_data",
            new_callable=AsyncMock,
            return_value=defaults["awaiting_reminder"],
        ),
        patch(
            "app.services.dispatcher.ConversationService.is_awaiting_limit_year_confirmation",
            new_callable=AsyncMock,
            return_value=defaults["awaiting_limit_year"],
        ),
        patch(
            "app.services.dispatcher.ConversationService.is_awaiting_limit_data",
            new_callable=AsyncMock,
            return_value=defaults["awaiting_limit_data"],
        ),
        patch(
            "app.services.dispatcher.ConversationService.is_awaiting_limit_delete_category",
            new_callable=AsyncMock,
            return_value=defaults["awaiting_limit_delete_category"],
        ),
        patch(
            "app.services.dispatcher.ConversationService.is_awaiting_limit_month_selection",
            new_callable=AsyncMock,
            return_value=defaults["awaiting_limit_month"],
        ),
        patch(
            "app.services.dispatcher.LLMService.process_message",
            new_callable=AsyncMock,
            return_value=defaults["llm"],
        ),
        patch(
            "app.services.dispatcher._update_ultimo_mensaje",
        ),
    ):
        yield


def created_result(**overrides):
    result = {
        "status": "created",
        "message": "ok",
        "limit_id": "abc-123",
        "category_name": "Ropa",
        "amount": Decimal("300000"),
        "month": 7,
        "year": 2026,
    }
    result.update(overrides)
    return LimitResult(**result)


class TestCreateLimitFlow:
    @pytest.mark.asyncio
    async def test_create_limit_registers_and_stores_last(self):
        with (
            limit_flow_patches(),
            patch(
                "app.services.dispatcher.LimitService.create_limit",
                return_value=created_result(),
            ),
            patch(
                "app.services.dispatcher.ConversationService.set_last_limit",
                new_callable=AsyncMock,
            ) as mock_set_last,
        ):
            result = await process_incoming_message("12345", "mi límite máximo para ropa será de 300.000")

        assert result.intent == "create_limit"
        assert result.service_invoked == "limit"
        assert "Registré tu límite para" in result.reply_text
        assert "Categoría: Ropa" in result.reply_text
        assert "300.000,00" in result.reply_text
        assert "cambiamos" in result.reply_text
        mock_set_last.assert_awaited_once()
        saved = mock_set_last.await_args.args[1]
        assert saved.category_name == "Ropa"

    @pytest.mark.asyncio
    async def test_create_limit_past_month_asks_year_confirmation(self):
        with (
            limit_flow_patches(
                llm=create_limit_llm(limit_month=1, limit_amount=None, limit_category=None),
            ),
            patch(
                "app.services.dispatcher.LimitService.create_limit",
                return_value=LimitResult(
                    status="needs_year_confirmation",
                    message="past",
                    proposed_month=1,
                    proposed_year=2027,
                ),
            ),
            patch(
                "app.services.dispatcher.ConversationService.set_pending_limit",
                new_callable=AsyncMock,
            ) as mock_pending,
        ):
            result = await process_incoming_message("12345", "establece un límite maximo para enero")

        assert "¿Quieres crear un límite de gastos para Enero de 2027?" in result.reply_text
        assert result.service_invoked == "limit"
        mock_pending.assert_awaited_once()
        assert mock_pending.await_args.kwargs["step"] == "awaiting_limit_year_confirmation"

    @pytest.mark.asyncio
    async def test_create_limit_missing_amount_asks(self):
        with (
            limit_flow_patches(llm=create_limit_llm(limit_amount=None)),
            patch(
                "app.services.dispatcher.LimitService.create_limit",
                return_value=LimitResult(
                    status="needs_amount",
                    message="amount",
                    category_name="Ropa",
                ),
            ),
            patch(
                "app.services.dispatcher.ConversationService.set_pending_limit",
                new_callable=AsyncMock,
            ) as mock_pending,
        ):
            result = await process_incoming_message("12345", "poné un límite para ropa")

        assert "monto" in result.reply_text.lower()
        mock_pending.assert_awaited_once()
        assert mock_pending.await_args.kwargs["step"] == "awaiting_limit_data"

    @pytest.mark.asyncio
    async def test_create_limit_missing_category_asks(self):
        with (
            limit_flow_patches(llm=create_limit_llm(limit_category=None)),
            patch(
                "app.services.dispatcher.LimitService.create_limit",
                return_value=LimitResult(
                    status="needs_category",
                    message="category",
                    amount=Decimal("300000"),
                ),
            ),
            patch(
                "app.services.dispatcher.ConversationService.set_pending_limit",
                new_callable=AsyncMock,
            ),
        ):
            result = await process_incoming_message("12345", "límite de 300000")

        assert "categoría" in result.reply_text.lower()


class TestChangeLimitFlow:
    @pytest.mark.asyncio
    async def test_change_limit_edits_last_created(self):
        last_limit = LastCreatedLimit(
            limit_id="abc-123",
            sender_phone="12345",
            category_name="Ropa",
            amount=Decimal("300000"),
            month=7,
            year=2026,
        )
        with (
            limit_flow_patches(
                llm=create_limit_llm(intent="change_limit", limit_month=8),
            ),
            patch(
                "app.services.dispatcher.ConversationService.get_last_limit",
                new_callable=AsyncMock,
                return_value=last_limit,
            ),
            patch(
                "app.services.dispatcher.LimitService.create_limit",
                return_value=created_result(month=8),
            ) as mock_create,
            patch(
                "app.services.dispatcher.ConversationService.set_last_limit",
                new_callable=AsyncMock,
            ),
        ):
            result = await process_incoming_message("12345", "mejor que sea para agosto")

        assert result.intent == "change_limit"
        assert "se Registró" in result.reply_text
        assert "Ropa" in result.reply_text
        assert "300.000,00" in result.reply_text
        call_data = mock_create.call_args.args[1]
        assert call_data["limit_month"] == 8

    @pytest.mark.asyncio
    async def test_change_limit_without_last_limit_guides_user(self):
        with (
            limit_flow_patches(llm=create_limit_llm(intent="change_limit")),
            patch(
                "app.services.dispatcher.ConversationService.get_last_limit",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await process_incoming_message("12345", "mejor que sea para agosto")

        assert "No tengo un límite reciente" in result.reply_text


class TestListLimitsFlow:
    @pytest.mark.asyncio
    async def test_list_limits_formats_entries(self):
        class FakeUser:
            id = "user-1"

        class FakeQuery:
            def filter(self, *a, **k):
                return self

            def first(self):
                return FakeUser()

        class FakeSession:
            def query(self, *a, **k):
                return FakeQuery()

            def close(self):
                pass

        from app.services.limit import LimitEntry, LimitListResult

        with (
            limit_flow_patches(llm={"intent": "list_limits", "reply_text": "consultando"}),
            patch("app.models.database.SessionLocal", lambda: FakeSession()),
            patch(
                "app.services.dispatcher.LimitService.list_limits",
                return_value=LimitListResult(
                    status="ok",
                    message="ok",
                    limits=[LimitEntry("Comida", Decimal("300000"), 7, 2026)],
                ),
            ),
        ):
            result = await process_incoming_message("12345", "mostrame mis límites")

        assert result.intent == "list_limits"
        assert "Comida" in result.reply_text
        assert "300.000,00" in result.reply_text

    @pytest.mark.asyncio
    async def test_list_limits_empty(self):
        class FakeUser:
            id = "user-1"

        class FakeQuery:
            def filter(self, *a, **k):
                return self

            def first(self):
                return FakeUser()

        class FakeSession:
            def query(self, *a, **k):
                return FakeQuery()

            def close(self):
                pass

        from app.services.limit import LimitListResult

        with (
            limit_flow_patches(llm={"intent": "list_limits", "reply_text": "consultando"}),
            patch("app.models.database.SessionLocal", lambda: FakeSession()),
            patch(
                "app.services.dispatcher.LimitService.list_limits",
                return_value=LimitListResult(status="ok", message="ok", limits=[]),
            ),
        ):
            result = await process_incoming_message("12345", "mostrame mis límites")

        assert "No tenés límites" in result.reply_text


class TestDeleteLimitFlow:
    @pytest.mark.asyncio
    async def test_delete_limit_single(self):
        with (
            limit_flow_patches(
                llm={
                    "intent": "delete_limit",
                    "limit_category": "Comida",
                    "limit_month": None,
                    "limit_year": None,
                    "reply_text": "procesando",
                },
            ),
            patch(
                "app.services.dispatcher.LimitService.delete_limit",
                return_value=LimitResult(
                    status="deleted",
                    message="ok",
                    category_name="Comida",
                    month=7,
                    year=2026,
                ),
            ),
        ):
            result = await process_incoming_message("12345", "eliminá el límite de comida")

        assert result.intent == "delete_limit"
        assert "eliminé el límite de Comida" in result.reply_text

    @pytest.mark.asyncio
    async def test_delete_limit_asks_month_selection(self):
        candidates = [
            {"limit_id": "a", "month": 7, "year": 2026, "amount": Decimal("300000")},
            {"limit_id": "b", "month": 11, "year": 2026, "amount": Decimal("400000")},
        ]
        with (
            limit_flow_patches(
                llm={
                    "intent": "delete_limit",
                    "limit_category": "Comida",
                    "limit_month": None,
                    "limit_year": None,
                    "reply_text": "procesando",
                },
            ),
            patch(
                "app.services.dispatcher.LimitService.delete_limit",
                return_value=LimitResult(
                    status="needs_month_selection",
                    message="select",
                    category_name="Comida",
                    candidates=candidates,
                ),
            ),
            patch(
                "app.services.dispatcher.ConversationService.set_pending_limit_delete",
                new_callable=AsyncMock,
            ) as mock_pending,
        ):
            result = await process_incoming_message("12345", "eliminá el límite de comida")

        assert "¿A cuál te referís?" in result.reply_text
        assert "300.000,00" in result.reply_text
        mock_pending.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_limit_without_category_asks(self):
        with (
            limit_flow_patches(
                llm={
                    "intent": "delete_limit",
                    "limit_category": None,
                    "limit_month": None,
                    "limit_year": None,
                    "reply_text": "procesando",
                },
            ),
            patch(
                "app.services.dispatcher.ConversationService.set_pending_limit_delete_category",
                new_callable=AsyncMock,
            ) as mock_pending,
        ):
            result = await process_incoming_message("12345", "eliminá un límite")

        assert "categoría" in result.reply_text.lower()
        mock_pending.assert_awaited_once()


class TestLimitMultiTurn:
    @pytest.mark.asyncio
    async def test_year_confirmation_confirm_creates(self):
        pending = PendingLimit(
            sender_phone="12345",
            category="Transporte",
            amount=Decimal("80000"),
            month=1,
            year=2027,
        )
        with (
            limit_flow_patches(
                awaiting_limit_year=True,
                llm={"intent": "confirm_limit", "reply_text": "dale"},
            ),
            patch(
                "app.services.dispatcher.ConversationService.get_pending_limit",
                new_callable=AsyncMock,
                return_value=pending,
            ),
            patch(
                "app.services.dispatcher.LimitService.create_limit",
                return_value=created_result(
                    category_name="Transporte",
                    amount=Decimal("80000"),
                    month=1,
                    year=2027,
                ),
            ),
            patch(
                "app.services.dispatcher.ConversationService.set_last_limit",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.dispatcher.ConversationService.clear_state",
                new_callable=AsyncMock,
            ) as mock_clear,
        ):
            result = await process_incoming_message("12345", "si")

        assert result.service_invoked == "conversation"
        assert "Registré tu límite para" in result.reply_text
        assert "Transporte" in result.reply_text
        assert "80.000,00" in result.reply_text
        mock_clear.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_year_confirmation_reject_cancels(self):
        pending = PendingLimit(
            sender_phone="12345",
            category=None,
            amount=None,
            month=1,
            year=2027,
        )
        with (
            limit_flow_patches(
                awaiting_limit_year=True,
                llm={"intent": "reject_limit", "reply_text": "no"},
            ),
            patch(
                "app.services.dispatcher.ConversationService.get_pending_limit",
                new_callable=AsyncMock,
                return_value=pending,
            ),
            patch(
                "app.services.dispatcher.ConversationService.clear_state",
                new_callable=AsyncMock,
            ) as mock_clear,
        ):
            result = await process_incoming_message("12345", "no")

        assert "no creé ningún límite" in result.reply_text
        mock_clear.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_year_confirmation_ambiguous_reasks(self):
        pending = PendingLimit(
            sender_phone="12345",
            category=None,
            amount=None,
            month=1,
            year=2027,
        )
        with (
            limit_flow_patches(
                awaiting_limit_year=True,
                llm={"intent": "greeting", "reply_text": "hola"},
            ),
            patch(
                "app.services.dispatcher.ConversationService.get_pending_limit",
                new_callable=AsyncMock,
                return_value=pending,
            ),
        ):
            result = await process_incoming_message("12345", "no sé")

        assert "¿Quieres crear un límite de gastos para Enero de 2027?" in result.reply_text

    @pytest.mark.asyncio
    async def test_year_confirmation_no_pending(self):
        with (
            limit_flow_patches(awaiting_limit_year=True),
            patch(
                "app.services.dispatcher.ConversationService.get_pending_limit",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.services.dispatcher.ConversationService.clear_state",
                new_callable=AsyncMock,
            ),
        ):
            result = await process_incoming_message("12345", "si")

        assert "contexto" in result.reply_text.lower()

    @pytest.mark.asyncio
    async def test_awaiting_limit_data_completes_with_amount(self):
        pending = PendingLimit(
            sender_phone="12345",
            category="Comida",
            amount=None,
            month=7,
            year=2026,
        )
        with (
            limit_flow_patches(
                awaiting_limit_data=True,
                llm={"intent": "create_limit", "limit_amount": 80000, "limit_month": None, "limit_year": None},
            ),
            patch(
                "app.services.dispatcher.ConversationService.get_pending_limit",
                new_callable=AsyncMock,
                return_value=pending,
            ),
            patch(
                "app.services.dispatcher.LimitService.create_limit",
                return_value=created_result(
                    category_name="Comida",
                    amount=Decimal("80000"),
                ),
            ) as mock_create,
            patch(
                "app.services.dispatcher.ConversationService.set_last_limit",
                new_callable=AsyncMock,
            ),
        ):
            result = await process_incoming_message("12345", "que sea de 80000")

        assert "Registré tu límite para" in result.reply_text
        assert "80.000,00" in result.reply_text
        call_data = mock_create.call_args.args[1]
        assert call_data["limit_amount"] == 80000
        assert call_data["limit_category"] == "Comida"

    @pytest.mark.asyncio
    async def test_awaiting_limit_data_missing_both(self):
        pending = PendingLimit(
            sender_phone="12345",
            category=None,
            amount=None,
            month=1,
            year=2027,
        )
        with (
            limit_flow_patches(
                awaiting_limit_data=True,
                llm={"intent": "create_limit", "limit_amount": None, "limit_month": None, "limit_year": None},
            ),
            patch(
                "app.services.dispatcher.ConversationService.get_pending_limit",
                new_callable=AsyncMock,
                return_value=pending,
            ),
            patch(
                "app.services.dispatcher.LimitService.create_limit",
                return_value=LimitResult(status="needs_category", message="cat"),
            ),
            patch(
                "app.services.dispatcher.ConversationService.set_pending_limit",
                new_callable=AsyncMock,
            ),
        ):
            result = await process_incoming_message("12345", "no sé")

        assert "categoría" in result.reply_text.lower()

    @pytest.mark.asyncio
    async def test_awaiting_limit_month_selection_deletes(self):
        pending_delete = PendingLimitDelete(
            sender_phone="12345",
            category_name="Comida",
            candidates=[{"limit_id": "b", "month": 11, "year": 2026, "amount": "400000"}],
        )
        with (
            limit_flow_patches(
                awaiting_limit_month=True,
                llm={"intent": "create_limit", "limit_month": 11, "limit_year": None},
            ),
            patch(
                "app.services.dispatcher.ConversationService.get_pending_limit_delete",
                new_callable=AsyncMock,
                return_value=pending_delete,
            ),
            patch(
                "app.services.dispatcher.LimitService.delete_limit",
                return_value=LimitResult(
                    status="deleted",
                    message="ok",
                    category_name="Comida",
                    month=11,
                    year=2026,
                ),
            ) as mock_delete,
            patch(
                "app.services.dispatcher.ConversationService.clear_state",
                new_callable=AsyncMock,
            ),
        ):
            result = await process_incoming_message("12345", "noviembre")

        assert "eliminé el límite de Comida" in result.reply_text
        assert mock_delete.call_args.kwargs["month"] == 11

    @pytest.mark.asyncio
    async def test_awaiting_limit_month_selection_no_month_reasks(self):
        pending_delete = PendingLimitDelete(
            sender_phone="12345",
            category_name="Comida",
            candidates=[{"limit_id": "b", "month": 11, "year": 2026, "amount": "400000"}],
        )
        with (
            limit_flow_patches(
                awaiting_limit_month=True,
                llm={"intent": "greeting", "limit_month": None, "reply_text": "hola"},
            ),
            patch(
                "app.services.dispatcher.ConversationService.get_pending_limit_delete",
                new_callable=AsyncMock,
                return_value=pending_delete,
            ),
        ):
            result = await process_incoming_message("12345", "no sé")

        assert "¿A cuál te referís?" in result.reply_text


class TestLimitMultiTurnFixes:
    @pytest.mark.asyncio
    async def test_awaiting_limit_data_extracts_amount_from_plain_number(self):
        """Flujo 1: '100000' suelto debe completar el monto sin depender del LLM."""
        pending = PendingLimit(
            sender_phone="12345",
            category="Ocio",
            amount=None,
            month=8,
            year=2026,
        )
        with (
            limit_flow_patches(
                awaiting_limit_data=True,
                llm={"intent": "expense", "amount": 100000, "limit_amount": None},
            ),
            patch(
                "app.services.dispatcher.ConversationService.get_pending_limit",
                new_callable=AsyncMock,
                return_value=pending,
            ),
            patch(
                "app.services.dispatcher.LimitService.create_limit",
                return_value=created_result(
                    category_name="Ocio",
                    amount=Decimal("100000"),
                ),
            ) as mock_create,
            patch(
                "app.services.dispatcher.ConversationService.set_last_limit",
                new_callable=AsyncMock,
            ),
        ):
            result = await process_incoming_message("12345", "100000")

        assert "Registré tu límite para" in result.reply_text
        call_data = mock_create.call_args.args[1]
        assert call_data["limit_amount"] == 100000
        assert call_data["limit_category"] == "Ocio"

    @pytest.mark.asyncio
    async def test_awaiting_limit_data_extracts_amount_when_llm_ignores(self):
        """Flujo 1: 'el limite es 100000' sin limit_amount del LLM."""
        pending = PendingLimit(
            sender_phone="12345",
            category="Ocio",
            amount=None,
            month=8,
            year=2026,
        )
        with (
            limit_flow_patches(
                awaiting_limit_data=True,
                llm={"intent": "out_of_scope", "limit_amount": None, "reply_text": "x"},
            ),
            patch(
                "app.services.dispatcher.ConversationService.get_pending_limit",
                new_callable=AsyncMock,
                return_value=pending,
            ),
            patch(
                "app.services.dispatcher.LimitService.create_limit",
                return_value=created_result(
                    category_name="Ocio",
                    amount=Decimal("100000"),
                ),
            ) as mock_create,
            patch(
                "app.services.dispatcher.ConversationService.set_last_limit",
                new_callable=AsyncMock,
            ),
        ):
            result = await process_incoming_message("12345", "el limite es 100000")

        assert "Registré tu límite para" in result.reply_text
        assert mock_create.call_args.args[1]["limit_amount"] == 100000

    @pytest.mark.asyncio
    async def test_awaiting_limit_data_cancel(self):
        """Flujo 1: 'cancelalo' debe cancelar el flujo y limpiar el estado."""
        pending = PendingLimit(
            sender_phone="12345",
            category="Ocio",
            amount=None,
            month=8,
            year=2026,
        )
        with (
            limit_flow_patches(
                awaiting_limit_data=True,
                llm={"intent": "reject_limit", "reply_text": "no"},
            ),
            patch(
                "app.services.dispatcher.ConversationService.get_pending_limit",
                new_callable=AsyncMock,
                return_value=pending,
            ),
            patch(
                "app.services.dispatcher.ConversationService.clear_state",
                new_callable=AsyncMock,
            ) as mock_clear,
        ):
            result = await process_incoming_message("12345", "cancelalo")

        assert "cancelé" in result.reply_text.lower()
        mock_clear.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_awaiting_limit_delete_category_provides_category(self):
        """Flujo 2: tras pedir la categoría, 'ocio' completa la eliminación por mes."""
        pending_delete = PendingLimitDelete(
            sender_phone="12345",
            category_name=None,
            month=9,
            year=2026,
        )
        with (
            limit_flow_patches(
                awaiting_limit_delete_category=True,
                llm={"intent": "out_of_scope", "limit_category": None, "reply_text": "x"},
            ),
            patch(
                "app.services.dispatcher.ConversationService.get_pending_limit_delete",
                new_callable=AsyncMock,
                return_value=pending_delete,
            ),
            patch(
                "app.services.dispatcher.LimitService.delete_limit",
                return_value=LimitResult(
                    status="deleted",
                    message="ok",
                    category_name="Ocio",
                    month=9,
                    year=2026,
                ),
            ) as mock_delete,
            patch(
                "app.services.dispatcher.ConversationService.clear_state",
                new_callable=AsyncMock,
            ),
        ):
            result = await process_incoming_message("12345", "ocio")

        assert "eliminé el límite de Ocio" in result.reply_text
        assert mock_delete.call_args.args[1] == "ocio"
        assert mock_delete.call_args.kwargs["month"] == 9

    @pytest.mark.asyncio
    async def test_awaiting_limit_month_selection_month_name_fallback(self):
        """Flujo 2: 'el de septiembre' resuelve el mes 9 aunque el LLM no lo devuelva."""
        pending_delete = PendingLimitDelete(
            sender_phone="12345",
            category_name="Ocio",
            candidates=[{"limit_id": "b", "month": 9, "year": 2026, "amount": "300000"}],
        )
        with (
            limit_flow_patches(
                awaiting_limit_month=True,
                llm={"intent": "greeting", "limit_month": None, "reply_text": "hola"},
            ),
            patch(
                "app.services.dispatcher.ConversationService.get_pending_limit_delete",
                new_callable=AsyncMock,
                return_value=pending_delete,
            ),
            patch(
                "app.services.dispatcher.LimitService.delete_limit",
                return_value=LimitResult(
                    status="deleted",
                    message="ok",
                    category_name="Ocio",
                    month=9,
                    year=2026,
                ),
            ) as mock_delete,
            patch(
                "app.services.dispatcher.ConversationService.clear_state",
                new_callable=AsyncMock,
            ),
        ):
            result = await process_incoming_message("12345", "el de septiembre")

        assert "eliminé el límite de Ocio" in result.reply_text
        assert mock_delete.call_args.kwargs["month"] == 9

    @pytest.mark.asyncio
    async def test_change_limit_month_edits_existing_limit(self):
        """Flujo 2: 'cambia el mes por agosto' debe editar el último límite, no crear otro."""
        last_limit = LastCreatedLimit(
            limit_id="abc-123",
            sender_phone="12345",
            category_name="Ocio",
            amount=Decimal("300000"),
            month=9,
            year=2026,
        )
        with (
            limit_flow_patches(
                llm=create_limit_llm(intent="change_limit", limit_month=8),
            ),
            patch(
                "app.services.dispatcher.ConversationService.get_last_limit",
                new_callable=AsyncMock,
                return_value=last_limit,
            ),
            patch(
                "app.services.dispatcher.LimitService.create_limit",
                return_value=created_result(month=8),
            ) as mock_create,
            patch(
                "app.services.dispatcher.ConversationService.set_last_limit",
                new_callable=AsyncMock,
            ),
        ):
            result = await process_incoming_message("12345", "cambia el mes por agosto")

        assert result.intent == "change_limit"
        assert "Agosto" in result.reply_text
        assert mock_create.call_args.kwargs["last_limit"] is last_limit
        assert mock_create.call_args.args[1]["limit_month"] == 8

    @pytest.mark.asyncio
    async def test_year_confirmation_edit_reuses_last_limit(self):
        """Flujo 2: confirmar el año de una edición debe conservar el limit_id."""
        pending = PendingLimit(
            sender_phone="12345",
            category="Ocio",
            amount=Decimal("300000"),
            month=1,
            year=2027,
            is_edit=True,
            limit_id="abc-123",
        )
        with (
            limit_flow_patches(
                awaiting_limit_year=True,
                llm={"intent": "confirm_limit", "reply_text": "dale"},
            ),
            patch(
                "app.services.dispatcher.ConversationService.get_pending_limit",
                new_callable=AsyncMock,
                return_value=pending,
            ),
            patch(
                "app.services.dispatcher.LimitService.create_limit",
                return_value=created_result(month=1, year=2027),
            ) as mock_create,
            patch(
                "app.services.dispatcher.ConversationService.set_last_limit",
                new_callable=AsyncMock,
            ),
        ):
            result = await process_incoming_message("12345", "si")

        assert "Registró tu límite para" in result.reply_text
        assert mock_create.call_args.kwargs["last_limit"].limit_id == "abc-123"
        assert mock_create.call_args.kwargs["last_limit"].month == 1
