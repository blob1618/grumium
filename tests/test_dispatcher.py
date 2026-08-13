"""Tests for the extracted message dispatcher."""

from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest

from app.services.dispatcher import process_incoming_message
from app.services.dashboard_link import DashboardLinkDecision, DashboardLinkResult
from app.services.finance import MovementRegistrationResult
from app.services.onboarding import OnboardingDecision, OnboardingResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def known_user():
    return OnboardingResult(OnboardingDecision.KNOWN_USER)


def send_invitation():
    return OnboardingResult(
        OnboardingDecision.SEND_INVITATION,
        registration_url="https://example.com/registro",
        invitation_ttl_minutes=30,
    )


def suppress_response():
    return OnboardingResult(OnboardingDecision.SUPPRESS_RESPONSE)


def onboarding_error():
    return OnboardingResult(OnboardingDecision.ERROR)


def movement_llm_result(**overrides):
    result = {
        "intent": "expense",
        "movement_type": "egreso",
        "amount": 5000,
        "currency": "ARS",
        "description": "supermercado",
        "expense": "supermercado",
        "category": "supermercado",
        "reply_text": "LLM dice registrado",
        "reminder_concept": None,
        "reminder_day": None,
        "reminder_amount": None,
        "reminder_currency": None,
        "reminder_id": None,
        "reminder_title": None,
        "reminder_date": None,
    }
    result.update(overrides)
    return result


def greeting_llm_result():
    return {
        "intent": "greeting",
        "reply_text": "¡Hola! Soy Luka.",
        "expense": None,
        "amount": None,
        "currency": "ARS",
        "movement_type": None,
        "category": None,
        "description": None,
        "reminder_concept": None,
        "reminder_day": None,
        "reminder_amount": None,
        "reminder_currency": None,
        "reminder_id": None,
        "reminder_title": None,
        "reminder_date": None,
    }


def registered_result():
    return MovementRegistrationResult(
        status="registered",
        message="registered",
        movement_id="mov-1",
        user_id="user-1",
        duplicate=False,
    )


def duplicate_result():
    return MovementRegistrationResult(
        status="duplicate",
        message="duplicate",
        movement_id="mov-1",
        user_id="user-1",
        duplicate=True,
    )


@contextmanager
def common_patches(**overrides):
    """Default set of patches required by most dispatch paths."""
    defaults = dict(
        onboarding=known_user(),
        llm=movement_llm_result(),
        register=registered_result(),
        awaiting_rename=False,
        awaiting_reminder=False,
    )
    defaults.update(overrides)

    with (
        patch(
            "app.services.dispatcher.OnboardingService.prepare_whatsapp_message",
            return_value=defaults["onboarding"],
        ),
        patch(
            "app.services.dispatcher.LLMService.process_message",
            new_callable=AsyncMock,
            return_value=defaults["llm"],
        ),
        patch(
            "app.services.dispatcher.FinanceService.register_movement_with_category",
            return_value=defaults["register"],
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
            "app.services.dispatcher.ConversationService.set_last_movement",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.dispatcher._update_ultimo_mensaje",
        ),
    ):
        yield


# ---------------------------------------------------------------------------
# Onboarding gate
# ---------------------------------------------------------------------------

class TestOnboardingGate:
    """Dispatcher must check onboarding before any processing."""

    @pytest.mark.asyncio
    async def test_unknown_user_gets_invitation(self):
        with patch(
            "app.services.dispatcher.OnboardingService.prepare_whatsapp_message",
            return_value=send_invitation(),
        ):
            result = await process_incoming_message("5491199990000", "hola")

        assert "registrate" in result.reply_text.lower() or "registro" in result.reply_text.lower()
        assert result.service_invoked == "onboarding"

    @pytest.mark.asyncio
    async def test_suppress_response_returns_empty(self):
        with patch(
            "app.services.dispatcher.OnboardingService.prepare_whatsapp_message",
            return_value=suppress_response(),
        ):
            result = await process_incoming_message("5491199990000", "hola")

        assert result.reply_text == ""
        assert result.service_invoked == "onboarding"

    @pytest.mark.asyncio
    async def test_onboarding_error(self):
        with patch(
            "app.services.dispatcher.OnboardingService.prepare_whatsapp_message",
            return_value=onboarding_error(),
        ):
            result = await process_incoming_message("5491199990000", "hola")

        assert "verificar" in result.reply_text.lower() or "intentá" in result.reply_text.lower()
        assert result.service_invoked == "onboarding"


# ---------------------------------------------------------------------------
# /link command
# ---------------------------------------------------------------------------

class TestLinkCommand:
    """The /link command bypasses LLM entirely."""

    def make_link_result(self):
        return DashboardLinkResult(
            DashboardLinkDecision.SEND_LINK,
            login_url="https://example.com/login?token=abc",
            link_ttl_minutes=15,
        )

    @pytest.mark.asyncio
    async def test_link_command_sends_dashboard_link(self):
        with (
            patch(
                "app.services.dispatcher.OnboardingService.prepare_whatsapp_message",
                return_value=known_user(),
            ),
            patch(
                "app.services.dispatcher.DashboardLinkService.generate_or_reuse",
                return_value=self.make_link_result(),
            ),
        ):
            result = await process_incoming_message("12345", "/link")

        assert "dashboard" in result.reply_text.lower() or "login" in result.reply_text.lower()
        assert result.service_invoked == "dashboard_link"

    @pytest.mark.asyncio
    async def test_link_command_case_insensitive_with_spaces(self):
        with (
            patch(
                "app.services.dispatcher.OnboardingService.prepare_whatsapp_message",
                return_value=known_user(),
            ),
            patch(
                "app.services.dispatcher.DashboardLinkService.generate_or_reuse",
                return_value=self.make_link_result(),
            ),
        ):
            result = await process_incoming_message("12345", "  /link  ")

        assert result.service_invoked == "dashboard_link"


# ---------------------------------------------------------------------------
# Financial movements
# ---------------------------------------------------------------------------

class TestFinancialMovement:
    """Dispatcher routes expense intents to FinanceService."""

    @pytest.mark.asyncio
    async def test_expense_registered_successfully(self):
        with common_patches():
            result = await process_incoming_message("12345", "Gasté 5000 en supermercado", "wamid.1")

        assert "✅" in result.reply_text
        assert "5000" in result.reply_text
        assert result.intent == "expense"
        assert result.service_invoked == "finance"
        assert result.raw_llm_response is not None
        assert result.raw_llm_response["intent"] == "expense"

    @pytest.mark.asyncio
    async def test_duplicate_movement_not_reregistered(self):
        with common_patches(register=duplicate_result()):
            result = await process_incoming_message("12345", "Gasté 5000 en supermercado", "wamid.1")

        assert "duplicado" in result.reply_text.lower() or "ya había" in result.reply_text.lower()


# ---------------------------------------------------------------------------
# Greeting / out_of_scope
# ---------------------------------------------------------------------------

class TestNonFinancialIntents:
    """Dispatcher returns LLM reply_text for non-financial intents."""

    @pytest.mark.asyncio
    async def test_greeting_returns_llm_reply(self):
        with common_patches(llm=greeting_llm_result()):
            result = await process_incoming_message("12345", "hola")

        assert result.reply_text == "¡Hola! Soy Luka."
        assert result.intent == "greeting"
        assert result.raw_llm_response is not None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge cases the dispatcher must handle gracefully."""

    @pytest.mark.asyncio
    async def test_empty_message(self):
        with common_patches(llm=greeting_llm_result()):
            result = await process_incoming_message("12345", "")

        assert result.reply_text  # must always return something

    @pytest.mark.asyncio
    async def test_whitespace_only_message(self):
        with common_patches(llm=greeting_llm_result()):
            result = await process_incoming_message("12345", "   ")

        assert result.reply_text


# ---------------------------------------------------------------------------
# Reminder intents
# ---------------------------------------------------------------------------

class TestReminderIntents:
    """Dispatcher routes reminder intents to ReminderService."""

    @pytest.mark.asyncio
    async def test_pause_reminder_routes_to_reminder_service(self):
        from app.services.reminder import ReminderResult

        llm_result = {
            "intent": "pause_reminder",
            "reminder_id": "123e4567-e89b-12d3-a456-426614174000",
            "reply_text": "Estoy pausando el recordatorio.",
        }

        with (
            patch(
                "app.services.dispatcher.OnboardingService.prepare_whatsapp_message",
                return_value=known_user(),
            ),
            patch(
                "app.services.dispatcher.LLMService.process_message",
                new_callable=AsyncMock,
                return_value=llm_result,
            ),
            patch(
                "app.services.dispatcher.ConversationService.is_awaiting_rename",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.services.dispatcher.ConversationService.is_awaiting_reminder_data",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.services.dispatcher._update_ultimo_mensaje",
            ),
            patch(
                "app.services.dispatcher.ReminderService.pause_reminder",
                return_value=ReminderResult(status="paused", message="ok"),
            ),
        ):
            result = await process_incoming_message("12345", "Pausá el recordatorio de luz")

        assert result.service_invoked == "reminder"
        assert "pausé" in result.reply_text.lower()
