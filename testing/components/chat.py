"""Chat component — message rendering, input, and export."""

import asyncio
import json
from pathlib import Path

import streamlit as st

from testing.components.debug_panel import render_debug
from testing.config.settings import TestingConfig
from testing.services.webhook_mode import WebhookModeService


def _public_asset(filename: str) -> Path:
    """Resolve a file inside the testing/public/ directory."""
    return Path(__file__).resolve().parent.parent / "public" / filename


def bot_avatar() -> bytes:
    """Return the Luka logo as avatar bytes for the assistant."""
    logo = _public_asset("logo-luka.png")
    if logo.exists():
        return logo.read_bytes()
    return None


def export_as_json(messages: list[dict]) -> str:
    """Export chat history as JSON string."""
    return json.dumps(messages, ensure_ascii=False, indent=2)


def export_as_text(messages: list[dict]) -> str:
    """Export chat history as human-readable text (no debug data)."""
    if not messages:
        return ""
    lines = []
    for msg in messages:
        role_label = "Usuario" if msg["role"] == "user" else "Luka"
        lines.append(f"{role_label}: {msg['content']}")
    return "\n".join(lines)


def _get_prompt_path(config: TestingConfig) -> str:
    """Resolve prompt path from config."""
    if config.prompt_path == "prompt.md":
        return "prompt.md"
    return f"testing/prompts/{config.prompt_path}"


async def _process_message(text: str, config: TestingConfig) -> tuple[str, dict]:
    """
    Procesa el mensaje a través del flujo completo del dispatcher (webhook).

    Returns (reply_text, debug_data).
    """
    service = WebhookModeService()
    result = await service.send_message(
        text=text,
        phone=config.phone,
        provider=config.provider,
        prompt_path=_get_prompt_path(config),
        model=config.model,
    )
    debug_data = {
        "raw_json": result.raw_llm_response,
        "latency_ms": result.latency_ms,
        "service_log": result.service_invoked or "unknown",
        "redis_state": result.redis_state,
        "provider": result.provider,
        "model": result.model,
        "prompt_used": result.prompt_path,
    }
    return result.reply_text, debug_data


def render_chat(config: TestingConfig) -> None:
    """Render the chat interface and handle user input."""

    # Display existing messages
    for msg in st.session_state.messages:
        if msg["role"] == "assistant":
            with st.chat_message("assistant", avatar=bot_avatar()):
                st.write(msg["content"])
                if msg.get("debug"):
                    flags = {
                        "json": config.debug_json,
                        "latency": config.debug_latency,
                        "redis": config.debug_redis,
                        "logs": config.debug_logs,
                    }
                    render_debug(msg["debug"], flags)
        else:
            with st.chat_message("user"):
                st.write(msg["content"])

    # Chat input
    if prompt := st.chat_input("Escribí un mensaje..."):
        # Add user message
        st.session_state.messages.append({
            "role": "user",
            "content": prompt,
            "debug": {},
        })
        with st.chat_message("user"):
            st.write(prompt)

        # Process and add assistant response
        with st.chat_message("assistant", avatar=bot_avatar()):
            with st.spinner("Procesando..."):
                reply_text, debug_data = asyncio.run(
                    _process_message(prompt, config)
                )

            raw = debug_data.get("raw_json") or {}
            if raw.get("error"):
                st.error(reply_text or "Error del LLM")
            else:
                st.write(reply_text or "Sin respuesta")

            flags = {
                "json": config.debug_json,
                "latency": config.debug_latency,
                "redis": config.debug_redis,
                "logs": config.debug_logs,
            }
            render_debug(debug_data, flags)

        st.session_state.messages.append({
            "role": "assistant",
            "content": reply_text or "Sin respuesta",
            "debug": debug_data,
        })

    # Export buttons in sidebar
    with st.sidebar:
        if st.session_state.messages:
            st.subheader("Exportar")
            json_data = export_as_json(st.session_state.messages)
            st.download_button(
                "💾 JSON",
                data=json_data,
                file_name="luka_test_chat.json",
                mime="application/json",
                key="export_json",
            )
            text_data = export_as_text(st.session_state.messages)
            st.download_button(
                "📄 Texto",
                data=text_data,
                file_name="luka_test_chat.txt",
                mime="text/plain",
                key="export_text",
            )
