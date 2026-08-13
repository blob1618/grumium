"""Tests for DirectModeService."""

from unittest.mock import AsyncMock, patch

import pytest

from testing.services.direct_mode import DirectModeResult, DirectModeService


def sample_llm_response(**overrides):
    result = {
        "intent": "expense",
        "amount": 5000,
        "currency": "ARS",
        "movement_type": "egreso",
        "description": "supermercado",
        "expense": "supermercado",
        "category": "alimentación",
        "reply_text": "Registré tu gasto.",
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


class TestDirectModeResult:
    def test_result_has_required_fields(self):
        result = DirectModeResult(
            reply_text="hola",
            raw_json={"intent": "greeting"},
            latency_ms=42.0,
            provider="gemini",
            prompt_path="prompt.md",
        )
        assert result.reply_text == "hola"
        assert result.raw_json["intent"] == "greeting"
        assert result.latency_ms == 42.0
        assert result.provider == "gemini"
        assert result.prompt_path == "prompt.md"


class TestSendMessage:
    @pytest.mark.asyncio
    async def test_returns_llm_response(self):
        service = DirectModeService()
        llm_response = sample_llm_response()

        with (
            patch(
                "testing.services.direct_mode.LLMService.process_message",
                new_callable=AsyncMock,
                return_value=llm_response,
            ),
            patch("testing.services.direct_mode.LLMService.reset_provider"),
            patch("testing.services.direct_mode.LLMService.set_prompt_path"),
        ):
            result = await service.send_message("Gasté 5000", "gemini", "prompt.md")

        assert result.reply_text == "Registré tu gasto."
        assert result.raw_json["intent"] == "expense"
        assert result.raw_json["amount"] == 5000
        assert result.provider == "gemini"
        assert result.prompt_path == "prompt.md"

    @pytest.mark.asyncio
    async def test_measures_latency(self):
        service = DirectModeService()

        with (
            patch(
                "testing.services.direct_mode.LLMService.process_message",
                new_callable=AsyncMock,
                return_value=sample_llm_response(),
            ),
            patch("testing.services.direct_mode.LLMService.reset_provider"),
            patch("testing.services.direct_mode.LLMService.set_prompt_path"),
        ):
            result = await service.send_message("test", "gemini", "prompt.md")

        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_sets_provider_via_env(self):
        service = DirectModeService()

        with (
            patch(
                "testing.services.direct_mode.LLMService.process_message",
                new_callable=AsyncMock,
                return_value=sample_llm_response(),
            ),
            patch("testing.services.direct_mode.LLMService.reset_provider") as mock_reset,
            patch("testing.services.direct_mode.LLMService.set_prompt_path"),
            patch.dict("os.environ", {"LLM_PROVIDER": "mistral"}),
        ):
            result = await service.send_message("test", "mistral", "prompt.md")

        mock_reset.assert_called_once()
        assert result.provider == "mistral"

    @pytest.mark.asyncio
    async def test_handles_llm_error_gracefully(self):
        service = DirectModeService()

        with (
            patch(
                "testing.services.direct_mode.LLMService.process_message",
                new_callable=AsyncMock,
                side_effect=Exception("API timeout"),
            ),
            patch("testing.services.direct_mode.LLMService.reset_provider"),
            patch("testing.services.direct_mode.LLMService.set_prompt_path"),
        ):
            result = await service.send_message("test", "gemini", "prompt.md")

        assert "error" in result.reply_text.lower() or result.raw_json.get("intent") == "out_of_scope"
        assert result.latency_ms >= 0


class TestGetAvailableProviders:
    def test_returns_provider_names(self):
        service = DirectModeService()
        providers = service.get_available_providers()

        assert "gemini" in providers
        assert "mistral" in providers
        assert isinstance(providers, list)

    def test_reads_from_factory(self):
        with patch(
            "testing.services.direct_mode._PROVIDERS",
            {"gemini": object, "mistral": object, "anthropic": object},
        ):
            service = DirectModeService()
            providers = service.get_available_providers()

        assert "anthropic" in providers
