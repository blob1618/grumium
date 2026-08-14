"""Webhook mode — simulates the full dispatcher pipeline."""

import os
import time
from dataclasses import dataclass

from app.services.dispatcher import process_incoming_message
from app.services.llm import LLMService
from app.services.conversation import ConversationService
from testing.config.settings import set_model_env


@dataclass
class WebhookModeResult:
    """Result of a full webhook simulation."""
    reply_text: str
    raw_llm_response: dict | None
    service_invoked: str | None
    intent: str | None
    latency_ms: float
    provider: str
    prompt_path: str
    redis_state: dict | None
    model: str = ""


class WebhookModeService:
    """Simulates the full webhook dispatch pipeline without HTTP."""

    async def send_message(
        self,
        text: str,
        phone: str,
        provider: str,
        prompt_path: str,
        model: str = "",
    ) -> WebhookModeResult:
        """
        Send a message through the full dispatcher pipeline.

        Configures the provider and prompt, invokes the dispatcher,
        captures Redis state, and measures latency.
        """
        os.environ["LLM_PROVIDER"] = provider
        set_model_env(provider, model)
        LLMService.reset_provider()
        LLMService.set_prompt_path(prompt_path)

        start = time.perf_counter()
        try:
            dispatch_result = await process_incoming_message(
                sender_phone=phone,
                text_body=text,
                whatsapp_message_id=None,
            )
            latency_ms = (time.perf_counter() - start) * 1000

            # Capture current Redis state for debug
            redis_state = None
            try:
                state = await ConversationService.get_state(phone)
                redis_state = state.to_dict()
            except Exception:
                redis_state = {"error": "Could not read Redis state"}

            return WebhookModeResult(
                reply_text=dispatch_result.reply_text,
                raw_llm_response=dispatch_result.raw_llm_response,
                service_invoked=dispatch_result.service_invoked,
                intent=dispatch_result.intent,
                latency_ms=latency_ms,
                provider=provider,
                prompt_path=prompt_path,
                redis_state=redis_state,
                model=model,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            return WebhookModeResult(
                reply_text=f"Error del dispatcher: {type(exc).__name__}: {exc}",
                raw_llm_response=None,
                service_invoked=None,
                intent=None,
                latency_ms=latency_ms,
                provider=provider,
                prompt_path=prompt_path,
                redis_state=None,
                model=model,
            )
