"""Direct LLM mode — calls LLMService bypassing the dispatcher."""

import os
import time
from dataclasses import dataclass

from app.services.llm import LLMService
from app.services.llm_providers.factory import _PROVIDERS


@dataclass
class DirectModeResult:
    """Result of a direct LLM invocation."""
    reply_text: str
    raw_json: dict
    latency_ms: float
    provider: str
    prompt_path: str


class DirectModeService:
    """Invokes LLMService directly for prompt/provider testing."""

    def get_available_providers(self) -> list[str]:
        """Return list of registered LLM provider names from factory."""
        return list(_PROVIDERS.keys())

    async def send_message(
        self,
        text: str,
        provider: str,
        prompt_path: str,
    ) -> DirectModeResult:
        """
        Send a message directly to LLMService.

        Configures the provider and prompt path, calls process_message,
        and measures latency.
        """
        # Configure provider
        os.environ["LLM_PROVIDER"] = provider
        LLMService.reset_provider()
        LLMService.set_prompt_path(prompt_path)

        start = time.perf_counter()
        try:
            raw_json = await LLMService.process_message(text)
            latency_ms = (time.perf_counter() - start) * 1000

            return DirectModeResult(
                reply_text=raw_json.get("reply_text", ""),
                raw_json=raw_json,
                latency_ms=latency_ms,
                provider=provider,
                prompt_path=prompt_path,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            return DirectModeResult(
                reply_text=f"Error del LLM: {type(exc).__name__}: {exc}",
                raw_json={"intent": "out_of_scope", "error": str(exc)},
                latency_ms=latency_ms,
                provider=provider,
                prompt_path=prompt_path,
            )
