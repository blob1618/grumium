"""Tests for WebhookModeService."""

import os
from unittest.mock import AsyncMock, patch

import pytest

from testing.services.webhook_mode import WebhookModeResult, WebhookModeService
from app.services.dispatcher import DispatchResult


def dispatch_result(**overrides):
    defaults = {
        "reply_text": "✅ Registré tu egreso: supermercado por $5000 ARS.",
        "raw_llm_response": {"intent": "expense", "amount": 5000},
        "service_invoked": "finance",
        "intent": "expense",
        "debug_info": {},
    }
    defaults.update(overrides)
    return DispatchResult(**defaults)


class TestWebhookModeResult:
    def test_result_has_required_fields(self):
        result = WebhookModeResult(
            reply_text="ok",
            raw_llm_response=None,
            service_invoked=None,
            intent=None,
            latency_ms=10.0,
            provider="gemini",
            prompt_path="prompt.md",
            redis_state=None,
        )
        assert result.reply_text == "ok"


class TestSendMessage:
    @pytest.mark.asyncio
    async def test_routes_through_dispatcher(self):
        service = WebhookModeService()

        with (
            patch(
                "testing.services.webhook_mode.process_incoming_message",
                new_callable=AsyncMock,
                return_value=dispatch_result(),
            ) as mock_dispatch,
            patch("testing.services.webhook_mode.LLMService.reset_provider"),
            patch("testing.services.webhook_mode.LLMService.set_prompt_path"),
        ):
            result = await service.send_message(
                text="Gasté 5000 en super",
                phone="12345",
                provider="gemini",
                prompt_path="prompt.md",
            )

        mock_dispatch.assert_awaited_once_with(
            sender_phone="12345",
            text_body="Gasté 5000 en super",
            whatsapp_message_id=None,
        )
        assert "5000" in result.reply_text
        assert result.service_invoked == "finance"
        assert result.intent == "expense"

    @pytest.mark.asyncio
    async def test_measures_latency(self):
        service = WebhookModeService()

        with (
            patch(
                "testing.services.webhook_mode.process_incoming_message",
                new_callable=AsyncMock,
                return_value=dispatch_result(),
            ),
            patch("testing.services.webhook_mode.LLMService.reset_provider"),
            patch("testing.services.webhook_mode.LLMService.set_prompt_path"),
        ):
            result = await service.send_message("test", "12345", "gemini", "prompt.md")

        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_captures_redis_state(self):
        service = WebhookModeService()

        with (
            patch(
                "testing.services.webhook_mode.process_incoming_message",
                new_callable=AsyncMock,
                return_value=dispatch_result(),
            ),
            patch("testing.services.webhook_mode.LLMService.reset_provider"),
            patch("testing.services.webhook_mode.LLMService.set_prompt_path"),
            patch(
                "testing.services.webhook_mode.ConversationService.get_state",
                new_callable=AsyncMock,
            ) as mock_state,
        ):
            from app.services.conversation import ConversationState
            mock_state.return_value = ConversationState.empty()

            result = await service.send_message("test", "12345", "gemini", "prompt.md")

        assert result.redis_state is not None
        assert result.redis_state["step"] == "none"

    @pytest.mark.asyncio
    async def test_handles_dispatcher_error(self):
        service = WebhookModeService()

        with (
            patch(
                "testing.services.webhook_mode.process_incoming_message",
                new_callable=AsyncMock,
                side_effect=Exception("DB connection failed"),
            ),
            patch("testing.services.webhook_mode.LLMService.reset_provider"),
            patch("testing.services.webhook_mode.LLMService.set_prompt_path"),
        ):
            result = await service.send_message("test", "12345", "gemini", "prompt.md")

        assert "error" in result.reply_text.lower()
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_redis_state_read_failure_returns_error_dict(self):
        service = WebhookModeService()

        with (
            patch(
                "testing.services.webhook_mode.process_incoming_message",
                new_callable=AsyncMock,
                return_value=dispatch_result(),
            ),
            patch("testing.services.webhook_mode.LLMService.reset_provider"),
            patch("testing.services.webhook_mode.LLMService.set_prompt_path"),
            patch(
                "testing.services.webhook_mode.ConversationService.get_state",
                new_callable=AsyncMock,
                side_effect=Exception("redis down"),
            ),
        ):
            result = await service.send_message("test", "12345", "gemini", "prompt.md")

        assert result.redis_state == {"error": "Could not read Redis state"}

    @pytest.mark.asyncio
    async def test_sets_model_via_env(self):
        service = WebhookModeService()

        with (
            patch(
                "testing.services.webhook_mode.process_incoming_message",
                new_callable=AsyncMock,
                return_value=dispatch_result(),
            ),
            patch("testing.services.webhook_mode.LLMService.reset_provider"),
            patch("testing.services.webhook_mode.LLMService.set_prompt_path"),
            patch.dict("os.environ", {}, clear=False),
        ):
            result = await service.send_message(
                "test", "12345", "gemini", "prompt.md", model="gemini-3.5-flash"
            )

        assert os.environ["GEMINI_MODEL"] == "gemini-3.5-flash"
        assert result.model == "gemini-3.5-flash"
