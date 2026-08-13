# Streamlit Testing Environment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Streamlit-based testing chat for the Luka financial assistant, with two operation modes (direct LLM / full webhook), configurable LLM provider/prompt, user simulation, and debug panels — all containerized via Docker Compose.

**Architecture:** Streamlit app in `testing/` imports production services from `app/` directly (no API layer). A dispatcher refactor extracts webhook logic from `main.py` into a reusable function both webhook and testing invoke. Docker Compose runs Streamlit + Redis; DB is SQLite embedded.

**Tech Stack:** Streamlit, Docker Compose, Redis, SQLite, pytest, existing FastAPI services (LLMService, FinanceService, ReminderService, ConversationService, OnboardingService)

**Spec:** `docs/superpowers/specs/2026-08-13-streamlit-testing-environment-design.md`

## Global Constraints

- Python 3.11
- No new dependencies in production `requirements.txt` (Streamlit deps go in `testing/requirements.txt`)
- All production tests must pass after dispatcher refactor (`python -m pytest -v`)
- All new tests must pass (`python -m pytest testing/tests/ -v`)
- Lint: `python -m ruff check .`
- `LLMService` singleton pattern: use `reset_provider()` and `set_prompt_path()` for config changes
- Redis optional in local, mandatory for multi-turn features
- `_PROVIDERS` dict in `app/services/llm_providers/factory.py` is the single source of truth for available providers
- SQLite for testing DB; monkeypatch `SessionLocal` same as existing tests
- Follow existing test patterns: `AsyncMock` for LLM/WhatsApp/Redis, `monkeypatch.setattr` for DB sessions

---

## File Structure

### New files (testing environment)
| File | Responsibility |
|------|---------------|
| `testing/Dockerfile` | Python 3.11 + Streamlit image |
| `testing/docker-compose.yml` | Streamlit + Redis services |
| `testing/requirements.txt` | Streamlit + testing-specific deps |
| `testing/app.py` | Streamlit entry point, wires components |
| `testing/config/__init__.py` | Package marker |
| `testing/config/settings.py` | Configuration dataclass, defaults |
| `testing/services/__init__.py` | Package marker |
| `testing/services/direct_mode.py` | Direct LLM invocation service |
| `testing/services/webhook_mode.py` | Full webhook flow simulation service |
| `testing/services/user_simulator.py` | Test user CRUD + seed data |
| `testing/components/__init__.py` | Package marker |
| `testing/components/sidebar.py` | Sidebar configuration panel |
| `testing/components/chat.py` | Chat message rendering + input |
| `testing/components/debug_panel.py` | Collapsible debug info per message |
| `testing/prompts/` | Directory for A/B test prompt files |
| `testing/tests/__init__.py` | Package marker |
| `testing/tests/conftest.py` | Shared fixtures (DB, mocks) |
| `testing/tests/test_direct_mode.py` | DirectModeService tests |
| `testing/tests/test_webhook_mode.py` | WebhookModeService tests |
| `testing/tests/test_user_simulator.py` | UserSimulator tests |
| `testing/tests/test_sidebar_config.py` | Sidebar config logic tests |
| `testing/tests/test_chat_state.py` | Chat state management tests |
| `testing/tests/test_debug_panel.py` | Debug panel rendering tests |

### Modified files (dispatcher refactor)
| File | Change |
|------|--------|
| `app/services/dispatcher.py` | **New** — extracted dispatcher logic from `main.py` |
| `app/main.py` | Thin webhook handler calling `dispatcher.process_incoming_message()` |
| `tests/test_dispatcher.py` | **New** — unit tests for extracted dispatcher |
| `tests/test_webhook.py` | Update mock paths from `app.main.*` to `app.services.dispatcher.*` |
| `tests/test_webhook_integration.py` | Update mock paths from `app.main.*` to `app.services.dispatcher.*` |

---

### Task 1: Dispatcher extraction — tests first

Extract the message processing logic from `app/main.py` into `app/services/dispatcher.py`. This is the foundation that both the webhook and the testing environment depend on. Start by writing tests for the new dispatcher function, then extract the code.

**Files:**
- Create: `app/services/dispatcher.py`
- Create: `tests/test_dispatcher.py`
- Modify: `app/main.py`
- Modify: `tests/test_webhook.py`
- Modify: `tests/test_webhook_integration.py`

**Interfaces:**
- Consumes: `LLMService.process_message(text)`, `FinanceService.register_movement_with_category(...)`, `FinanceService.register_movement_from_whatsapp_text(...)`, `ReminderService.create_reminder(...)`, `ConversationService.get_state(...)`, `OnboardingService.prepare_whatsapp_message(...)`, `DashboardLinkService.generate_or_reuse(...)`
- Produces: `async def process_incoming_message(sender_phone: str, text_body: str, whatsapp_message_id: str | None = None) -> DispatchResult` — returns a dataclass with `reply_text: str`, `raw_llm_response: dict | None`, `service_invoked: str | None`, `intent: str | None`

- [ ] **Step 1: Define the DispatchResult dataclass and function signature**

Create the new file with just the types and function stub:

```python
# app/services/dispatcher.py
"""
Message dispatcher — routes incoming user messages to the appropriate service.

Extracted from app/main.py so both the WhatsApp webhook and the testing
environment can invoke the same logic.
"""

import os
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.sql import func

from app.services.finance import FinanceService, MovementRegistrationResult
from app.services.llm import LLMService
from app.services.onboarding import OnboardingDecision, OnboardingService
from app.services.dashboard_link import DashboardLinkDecision, DashboardLinkService
from app.services.reminder import ReminderListResult, ReminderResult, ReminderService
from app.services.conversation import (
    ConversationService,
    LastRegisteredMovement,
    PendingMovement,
    PendingReminder,
)


@dataclass
class DispatchResult:
    """Result of processing an incoming message."""
    reply_text: str
    raw_llm_response: dict | None = None
    service_invoked: str | None = None
    intent: str | None = None
    debug_info: dict = field(default_factory=dict)


async def process_incoming_message(
    sender_phone: str,
    text_body: str,
    whatsapp_message_id: str | None = None,
) -> DispatchResult:
    """
    Process an incoming text message through the full dispatch pipeline.

    This includes:
    1. Onboarding check
    2. /link command interception
    3. Multi-turn state checks (rename, reminder data, category confirmation)
    4. LLM processing
    5. Intent dispatch (financial movement, reminders, categories, etc.)

    Args:
        sender_phone: The sender's WhatsApp phone number.
        text_body: The raw text body of the message.
        whatsapp_message_id: Optional WhatsApp message ID for dedup.

    Returns:
        DispatchResult with reply_text and debug metadata.
    """
    raise NotImplementedError("Dispatcher not yet implemented")
```

- [ ] **Step 2: Write failing tests for DispatchResult and core dispatch paths**

```python
# tests/test_dispatcher.py
"""Tests for the extracted message dispatcher."""

import os
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.dispatcher import DispatchResult, process_incoming_message
from app.services.finance import MovementRegistrationResult
from app.services.onboarding import OnboardingDecision, OnboardingResult
from app.services.dashboard_link import DashboardLinkDecision, DashboardLinkResult
from app.services.reminder import ReminderResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def known_user():
    return OnboardingResult(OnboardingDecision.KNOWN_USER)


def send_invitation():
    result = OnboardingResult(OnboardingDecision.SEND_INVITATION)
    result.registration_url = "https://example.com/registro"
    result.invitation_ttl_minutes = 30
    return result


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
        "category": None,
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

    @pytest.mark.asyncio
    async def test_link_command_sends_dashboard_link(self):
        link_result = DashboardLinkResult(DashboardLinkDecision.SEND_LINK)
        link_result.login_url = "https://example.com/login?token=abc"
        link_result.link_ttl_minutes = 15

        with (
            patch(
                "app.services.dispatcher.OnboardingService.prepare_whatsapp_message",
                return_value=known_user(),
            ),
            patch(
                "app.services.dispatcher.DashboardLinkService.generate_or_reuse",
                return_value=link_result,
            ),
        ):
            result = await process_incoming_message("12345", "/link")

        assert "dashboard" in result.reply_text.lower() or "login" in result.reply_text.lower()
        assert result.service_invoked == "dashboard_link"

    @pytest.mark.asyncio
    async def test_link_command_case_insensitive_with_spaces(self):
        link_result = DashboardLinkResult(DashboardLinkDecision.SEND_LINK)
        link_result.login_url = "https://example.com/login?token=abc"
        link_result.link_ttl_minutes = 15

        with (
            patch(
                "app.services.dispatcher.OnboardingService.prepare_whatsapp_message",
                return_value=known_user(),
            ),
            patch(
                "app.services.dispatcher.DashboardLinkService.generate_or_reuse",
                return_value=link_result,
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
        with (
            patch(
                "app.services.dispatcher.OnboardingService.prepare_whatsapp_message",
                return_value=known_user(),
            ),
            patch(
                "app.services.dispatcher.LLMService.process_message",
                new_callable=AsyncMock,
                return_value=movement_llm_result(),
            ),
            patch(
                "app.services.dispatcher.FinanceService.register_movement_with_category",
                return_value=registered_result(),
            ) as mock_register,
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
                "app.services.dispatcher.ConversationService.set_last_movement",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.dispatcher._update_ultimo_mensaje",
            ),
        ):
            result = await process_incoming_message("12345", "Gasté 5000 en supermercado", "wamid.1")

        assert "✅" in result.reply_text
        assert "5000" in result.reply_text
        assert result.intent == "expense"
        assert result.service_invoked == "finance"
        assert result.raw_llm_response is not None
        assert result.raw_llm_response["intent"] == "expense"

    @pytest.mark.asyncio
    async def test_duplicate_movement_not_reregistered(self):
        with (
            patch(
                "app.services.dispatcher.OnboardingService.prepare_whatsapp_message",
                return_value=known_user(),
            ),
            patch(
                "app.services.dispatcher.LLMService.process_message",
                new_callable=AsyncMock,
                return_value=movement_llm_result(),
            ),
            patch(
                "app.services.dispatcher.FinanceService.register_movement_with_category",
                return_value=duplicate_result(),
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
        ):
            result = await process_incoming_message("12345", "Gasté 5000 en supermercado", "wamid.1")

        assert "duplicado" in result.reply_text.lower() or "ya había" in result.reply_text.lower()


# ---------------------------------------------------------------------------
# Greeting / out_of_scope
# ---------------------------------------------------------------------------

class TestNonFinancialIntents:
    """Dispatcher returns LLM reply_text for non-financial intents."""

    @pytest.mark.asyncio
    async def test_greeting_returns_llm_reply(self):
        with (
            patch(
                "app.services.dispatcher.OnboardingService.prepare_whatsapp_message",
                return_value=known_user(),
            ),
            patch(
                "app.services.dispatcher.LLMService.process_message",
                new_callable=AsyncMock,
                return_value=greeting_llm_result(),
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
        ):
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
        with (
            patch(
                "app.services.dispatcher.OnboardingService.prepare_whatsapp_message",
                return_value=known_user(),
            ),
            patch(
                "app.services.dispatcher.LLMService.process_message",
                new_callable=AsyncMock,
                return_value=greeting_llm_result(),
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
        ):
            result = await process_incoming_message("12345", "")

        assert result.reply_text  # must always return something

    @pytest.mark.asyncio
    async def test_whitespace_only_message(self):
        with (
            patch(
                "app.services.dispatcher.OnboardingService.prepare_whatsapp_message",
                return_value=known_user(),
            ),
            patch(
                "app.services.dispatcher.LLMService.process_message",
                new_callable=AsyncMock,
                return_value=greeting_llm_result(),
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
        ):
            result = await process_incoming_message("12345", "   ")

        assert result.reply_text
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_dispatcher.py -v`
Expected: All tests FAIL with `NotImplementedError: Dispatcher not yet implemented`

- [ ] **Step 4: Move helper functions from main.py to dispatcher.py**

Move these functions from `app/main.py` to `app/services/dispatcher.py` (cut from main, paste into dispatcher):

- `_is_financial_movement`
- `_movement_description`
- `_format_amount`
- `_registered_reply`
- `_category_hint_reply`
- `_category_confirmation_reply`
- `_category_changed_reply`
- `_category_deleted_reply`
- `_category_not_found_reply`
- `_format_categories_list`
- `_registration_reply`
- `_safe_non_stk35_reply`
- `_update_ultimo_mensaje`
- `_is_create_reminder`
- `_CONCEPT_EXTRACTOR`, `_VERBOS_ACCION`, `_extract_concept_from_text`, `_validate_reminder_concept`
- `_reminder_creation_reply`
- `_reminder_list_reply`
- `_reminder_update_reply`
- `_reminder_state_reply`
- `_reminder_delete_reply`
- `_handle_list_reminders`
- `_onboarding_invitation_reply`
- `_dashboard_link_reply`
- `_DASHBOARD_LINK_NOT_ELIGIBLE_REPLY`
- `_handle_change_category`
- `_handle_delete_category`
- `_handle_list_categories`
- `_register_and_reply_with_hint`

All functions move exactly as-is. No logic changes. The imports they need move with them.

- [ ] **Step 5: Implement process_incoming_message**

Replace the `raise NotImplementedError` in `process_incoming_message` with the actual dispatch logic extracted from `handle_webhook` in `main.py`. The logic is the body of the `for message in messages:` loop, but instead of calling `send_whatsapp_message`, it returns a `DispatchResult`.

Key mapping:
- Where `main.py` did `await send_whatsapp_message(sender_phone, reply_text)` followed by `continue`, the dispatcher returns `DispatchResult(reply_text=reply_text, service_invoked="...", ...)`
- Populate `raw_llm_response` whenever `LLMService.process_message()` was called
- Populate `service_invoked` with the name of the service that handled the intent (e.g., `"onboarding"`, `"dashboard_link"`, `"finance"`, `"reminder"`, `"conversation"`, `"llm"`)
- Populate `intent` from `extracted_data.get("intent")`

The function must follow this exact pipeline order (same as current `main.py`):
1. Onboarding check — return early if not KNOWN_USER
2. `/link` command check — return early if matched
3. `_update_ultimo_mensaje`
4. Multi-turn: awaiting rename — handle and return
5. Multi-turn: awaiting reminder data — handle and return
6. LLM process message
7. Intent dispatch (change_category, delete_category, list_categories, list_reminders, update_reminder, pause_reminder, activate_reminder, delete_reminder, expense, create_reminder, greeting/out_of_scope, fallback legacy branch)

- [ ] **Step 6: Update main.py to call dispatcher**

Replace the entire `for message in messages:` body in `handle_webhook` with:

```python
# app/main.py — inside handle_webhook, replacing the for loop body
from app.services.dispatcher import process_incoming_message

# ... inside the for message in messages loop:
if message_type != "text":
    continue

whatsapp_message_id = message.get("id")
text_body = message.get("text", {}).get("body", "")

result = await process_incoming_message(
    sender_phone=sender_phone,
    text_body=text_body,
    whatsapp_message_id=whatsapp_message_id,
)

if result.reply_text:
    await send_whatsapp_message(sender_phone, result.reply_text)
```

Remove all the moved helper functions and handler functions from `main.py`. Keep only: `lifespan`, `app`, `VERIFY_TOKEN`, `read_root`, `test_redis`, `verify_webhook`, `handle_webhook`.

- [ ] **Step 7: Update mock paths in existing webhook tests**

In `tests/test_webhook.py`, update the `post_webhook_with_mocks` function and all other patches that reference `app.main.*` to reference `app.services.dispatcher.*` instead. Specifically:

- `"app.main.OnboardingService.prepare_whatsapp_message"` changes to `"app.services.dispatcher.OnboardingService.prepare_whatsapp_message"`
- `"app.main.LLMService.process_message"` changes to `"app.services.dispatcher.LLMService.process_message"`
- `"app.main.FinanceService.register_movement_from_whatsapp_text"` changes to `"app.services.dispatcher.FinanceService.register_movement_from_whatsapp_text"`
- `"app.main.FinanceService.register_movement_with_category"` changes to `"app.services.dispatcher.FinanceService.register_movement_with_category"`
- `"app.main.send_whatsapp_message"` stays as `"app.main.send_whatsapp_message"` (it's still called from main)
- All `ConversationService` patches change to `"app.services.dispatcher.ConversationService.*"`
- All `ReminderService` patches change to `"app.services.dispatcher.ReminderService.*"`
- All `DashboardLinkService` patches change to `"app.services.dispatcher.DashboardLinkService.*"`

Do the same for `tests/test_webhook_integration.py`.

- [ ] **Step 8: Run all tests to verify**

Run: `python -m pytest -v`
Expected: ALL tests pass (existing + new dispatcher tests)

Run: `python -m ruff check .`
Expected: No lint errors

- [ ] **Step 9: Commit**

```bash
git add app/services/dispatcher.py tests/test_dispatcher.py app/main.py tests/test_webhook.py tests/test_webhook_integration.py
git commit -m "refactor: extract message dispatcher from main.py

Move ~500 lines of dispatch logic into app/services/dispatcher.py.
Both the WhatsApp webhook and the testing environment now invoke
process_incoming_message() directly. DispatchResult carries reply_text
plus debug metadata (raw LLM response, service invoked, intent).

Existing webhook tests updated to patch dispatcher module paths."
```

---

### Task 2: Docker + project scaffolding

Set up the Docker infrastructure and project skeleton for the testing environment.

**Files:**
- Create: `testing/Dockerfile`
- Create: `testing/docker-compose.yml`
- Create: `testing/requirements.txt`
- Create: `testing/app.py` (minimal running Streamlit app)
- Create: `testing/config/__init__.py`
- Create: `testing/config/settings.py`
- Create: `testing/services/__init__.py`
- Create: `testing/components/__init__.py`
- Create: `testing/prompts/` (empty dir, with `.gitkeep`)
- Create: `testing/tests/__init__.py`
- Create: `testing/tests/conftest.py`

**Interfaces:**
- Consumes: nothing (foundation task)
- Produces: `TestingConfig` dataclass from `testing/config/settings.py`, shared pytest fixtures in `testing/tests/conftest.py`, running Docker container

- [ ] **Step 1: Create requirements.txt**

```txt
# testing/requirements.txt
# Inherits project deps + adds Streamlit
-r ../requirements.txt
streamlit>=1.45.0,<2.0.0
```

- [ ] **Step 2: Create Dockerfile**

```dockerfile
# testing/Dockerfile
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV TZ="America/Argentina/Buenos_Aires"

WORKDIR /app

# Install dependencies
COPY testing/requirements.txt /app/testing/requirements.txt
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r testing/requirements.txt

# Copy project code
COPY . /app/

EXPOSE 8501

CMD ["streamlit", "run", "testing/app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
```

- [ ] **Step 3: Create docker-compose.yml**

```yaml
# testing/docker-compose.yml
services:
  streamlit:
    build:
      context: ..
      dockerfile: testing/Dockerfile
    ports:
      - "8501:8501"
    volumes:
      - ..:/app
    env_file:
      - ../.env
    environment:
      - REDIS_URL=redis://redis:6379
      - DATABASE_URL=sqlite:///./testing_luka.db
    depends_on:
      - redis
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    ports:
      - "6380:6379"
    restart: unless-stopped
```

- [ ] **Step 4: Create config/settings.py**

```python
# testing/config/settings.py
"""Configuration for the Streamlit testing environment."""

from dataclasses import dataclass, field


@dataclass
class TestingConfig:
    """Holds all sidebar configuration state."""
    mode: str = "direct"                      # "direct" | "webhook"
    provider: str = "gemini"                  # LLM provider name
    prompt_path: str = "prompt.md"            # path to prompt file
    user_registered: bool = True              # simulate registered user
    phone: str = "5491112345678"              # simulated phone number
    user_name: str = "Test User"              # simulated user name
    debug_json: bool = True                   # show raw LLM JSON
    debug_latency: bool = True                # show latency metrics
    debug_redis: bool = True                  # show Redis state
    debug_logs: bool = True                   # show dispatcher logs


@dataclass
class ChatMessage:
    """A single message in the chat history."""
    role: str                                 # "user" | "assistant"
    content: str                              # visible text
    debug: dict = field(default_factory=dict) # debug metadata (assistant only)
```

- [ ] **Step 5: Create config/__init__.py**

```python
# testing/config/__init__.py
from .settings import TestingConfig, ChatMessage

__all__ = ["TestingConfig", "ChatMessage"]
```

- [ ] **Step 6: Create package markers**

```python
# testing/services/__init__.py
# testing/components/__init__.py
# testing/tests/__init__.py
```

Empty `__init__.py` files for all three packages.

- [ ] **Step 7: Create prompts/.gitkeep**

```
# testing/prompts/.gitkeep
```

Empty file to keep the directory in git.

- [ ] **Step 8: Create conftest.py with shared fixtures**

```python
# testing/tests/conftest.py
"""Shared fixtures for testing environment tests."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

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
        id=str(uuid.uuid4()),
        nombre="Test User",
        whatsapp_id="5491112345678",
    )
    session.add(user)
    session.commit()
    return {"user": user, "session": session, "SessionLocal": in_memory_db["SessionLocal"]}
```

- [ ] **Step 9: Create minimal app.py**

```python
# testing/app.py
"""Luka Testing Environment — Streamlit entry point."""

import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

st.set_page_config(
    page_title="Luka Testing",
    page_icon="🧪",
    layout="wide",
)

st.title("🧪 Luka Testing Environment")
st.caption("Entorno de testing para el asistente financiero Luka")

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []

if "config" not in st.session_state:
    from testing.config.settings import TestingConfig
    st.session_state.config = TestingConfig()

# Placeholder sidebar
with st.sidebar:
    st.header("Configuración")
    st.info("Panel de configuración — próximamente")

# Placeholder chat
st.info("Chat — próximamente")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
```

- [ ] **Step 10: Build and verify Docker runs**

Run:
```bash
docker compose -f testing/docker-compose.yml build
docker compose -f testing/docker-compose.yml up -d
```
Expected: Streamlit accessible at `http://localhost:8501` showing the placeholder page.

Run:
```bash
docker compose -f testing/docker-compose.yml down
```

- [ ] **Step 11: Commit**

```bash
git add testing/
git commit -m "feat: scaffold Streamlit testing environment

Docker Compose with Streamlit + Redis. Config dataclass, shared
test fixtures, placeholder UI. No functionality yet."
```

---

### Task 3: UserSimulator service

CRUD service for managing test users in the database during testing sessions.

**Files:**
- Create: `testing/services/user_simulator.py`
- Create: `testing/tests/test_user_simulator.py`

**Interfaces:**
- Consumes: `app.models.database.SessionLocal`, `app.models.database.Usuario`, `app.models.database.Categoria`, `app.models.database.MovimientoFinanciero`, `app.models.database.Recordatorio`
- Produces: `UserSimulator` class with methods: `create_test_user(phone: str, name: str) -> Usuario`, `delete_test_user(phone: str) -> None`, `reset_user_data(phone: str) -> None`, `seed_categories(phone: str, categories: list[str]) -> list[Categoria]`, `get_user(phone: str) -> Usuario | None`

- [ ] **Step 1: Write failing tests**

```python
# testing/tests/test_user_simulator.py
"""Tests for UserSimulator service."""

import pytest

from testing.services.user_simulator import UserSimulator
from app.models.database import Usuario, Categoria, MovimientoFinanciero


class TestCreateUser:
    def test_creates_user_with_phone_and_name(self, in_memory_db):
        sim = UserSimulator(in_memory_db["SessionLocal"])
        user = sim.create_test_user("5491100001111", "María Test")

        assert user.whatsapp_id == "5491100001111"
        assert user.nombre == "María Test"
        assert user.id is not None

    def test_create_duplicate_returns_existing(self, in_memory_db):
        sim = UserSimulator(in_memory_db["SessionLocal"])
        user1 = sim.create_test_user("5491100001111", "María")
        user2 = sim.create_test_user("5491100001111", "María Distinta")

        assert user1.id == user2.id

    def test_get_user_returns_none_when_not_exists(self, in_memory_db):
        sim = UserSimulator(in_memory_db["SessionLocal"])
        assert sim.get_user("9999999999") is None


class TestDeleteUser:
    def test_deletes_existing_user(self, in_memory_db):
        sim = UserSimulator(in_memory_db["SessionLocal"])
        sim.create_test_user("5491100001111", "María")
        sim.delete_test_user("5491100001111")

        assert sim.get_user("5491100001111") is None

    def test_delete_nonexistent_user_no_error(self, in_memory_db):
        sim = UserSimulator(in_memory_db["SessionLocal"])
        sim.delete_test_user("9999999999")  # should not raise


class TestResetUserData:
    def test_clears_movements_and_categories(self, in_memory_db):
        sim = UserSimulator(in_memory_db["SessionLocal"])
        user = sim.create_test_user("5491100001111", "María")
        sim.seed_categories("5491100001111", ["comida", "transporte"])

        sim.reset_user_data("5491100001111")

        # User still exists
        assert sim.get_user("5491100001111") is not None
        # But categories are gone
        session = in_memory_db["SessionLocal"]()
        cats = session.query(Categoria).filter(Categoria.usuario_id == user.id).all()
        session.close()
        assert len(cats) == 0

    def test_reset_nonexistent_user_no_error(self, in_memory_db):
        sim = UserSimulator(in_memory_db["SessionLocal"])
        sim.reset_user_data("9999999999")  # should not raise


class TestSeedCategories:
    def test_creates_categories_for_user(self, in_memory_db):
        sim = UserSimulator(in_memory_db["SessionLocal"])
        sim.create_test_user("5491100001111", "María")
        cats = sim.seed_categories("5491100001111", ["comida", "transporte", "salud"])

        assert len(cats) == 3
        assert {c.nombre for c in cats} == {"comida", "transporte", "salud"}

    def test_seed_idempotent_no_duplicates(self, in_memory_db):
        sim = UserSimulator(in_memory_db["SessionLocal"])
        sim.create_test_user("5491100001111", "María")
        sim.seed_categories("5491100001111", ["comida", "comida"])

        session = in_memory_db["SessionLocal"]()
        cats = session.query(Categoria).all()
        session.close()
        assert len(cats) == 1

    def test_seed_without_user_raises(self, in_memory_db):
        sim = UserSimulator(in_memory_db["SessionLocal"])
        with pytest.raises(ValueError, match="usuario"):
            sim.seed_categories("9999999999", ["comida"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest testing/tests/test_user_simulator.py -v`
Expected: FAIL — `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: Implement UserSimulator**

```python
# testing/services/user_simulator.py
"""Test user management for the Streamlit testing environment."""

import uuid

from app.models.database import (
    Categoria,
    MovimientoFinanciero,
    Recordatorio,
    Usuario,
)


class UserSimulator:
    """CRUD operations for test users in the database."""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def create_test_user(self, phone: str, name: str) -> Usuario:
        """Create a test user. Returns existing user if phone already exists."""
        session = self._session_factory()
        try:
            existing = session.query(Usuario).filter(
                Usuario.whatsapp_id == phone
            ).first()
            if existing:
                return existing

            user = Usuario(
                id=str(uuid.uuid4()),
                nombre=name,
                whatsapp_id=phone,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            return user
        finally:
            session.close()

    def get_user(self, phone: str) -> Usuario | None:
        """Look up a user by phone number."""
        session = self._session_factory()
        try:
            return session.query(Usuario).filter(
                Usuario.whatsapp_id == phone
            ).first()
        finally:
            session.close()

    def delete_test_user(self, phone: str) -> None:
        """Delete a test user and all associated data."""
        session = self._session_factory()
        try:
            user = session.query(Usuario).filter(
                Usuario.whatsapp_id == phone
            ).first()
            if user is None:
                return

            session.query(MovimientoFinanciero).filter(
                MovimientoFinanciero.usuario_id == user.id
            ).delete()
            session.query(Recordatorio).filter(
                Recordatorio.usuario_id == user.id
            ).delete()
            session.query(Categoria).filter(
                Categoria.usuario_id == user.id
            ).delete()
            session.delete(user)
            session.commit()
        finally:
            session.close()

    def reset_user_data(self, phone: str) -> None:
        """Delete all movements, categories, and reminders for a user. User stays."""
        session = self._session_factory()
        try:
            user = session.query(Usuario).filter(
                Usuario.whatsapp_id == phone
            ).first()
            if user is None:
                return

            session.query(MovimientoFinanciero).filter(
                MovimientoFinanciero.usuario_id == user.id
            ).delete()
            session.query(Recordatorio).filter(
                Recordatorio.usuario_id == user.id
            ).delete()
            session.query(Categoria).filter(
                Categoria.usuario_id == user.id
            ).delete()
            session.commit()
        finally:
            session.close()

    def seed_categories(self, phone: str, categories: list[str]) -> list[Categoria]:
        """Create categories for a user. Skips duplicates."""
        session = self._session_factory()
        try:
            user = session.query(Usuario).filter(
                Usuario.whatsapp_id == phone
            ).first()
            if user is None:
                raise ValueError(f"No se encontró el usuario con teléfono {phone}")

            created = []
            for cat_name in categories:
                existing = session.query(Categoria).filter(
                    Categoria.usuario_id == user.id,
                    Categoria.nombre == cat_name,
                ).first()
                if existing:
                    continue

                cat = Categoria(
                    id=str(uuid.uuid4()),
                    nombre=cat_name,
                    usuario_id=user.id,
                )
                session.add(cat)
                created.append(cat)

            session.commit()
            for c in created:
                session.refresh(c)
            return created
        finally:
            session.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest testing/tests/test_user_simulator.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add testing/services/user_simulator.py testing/tests/test_user_simulator.py
git commit -m "feat: UserSimulator for test user CRUD and seeding"
```

---

### Task 4: DirectModeService

Service that calls LLMService directly, bypassing all webhook/dispatch logic.

**Files:**
- Create: `testing/services/direct_mode.py`
- Create: `testing/tests/test_direct_mode.py`

**Interfaces:**
- Consumes: `app.services.llm.LLMService.process_message(text) -> dict`, `app.services.llm.LLMService.reset_provider()`, `app.services.llm.LLMService.set_prompt_path(path)`, `app.services.llm_providers.factory._PROVIDERS` (dict of provider names)
- Produces: `DirectModeService` class with method `async def send_message(text: str, provider: str, prompt_path: str) -> DirectModeResult` where `DirectModeResult` has `reply_text: str`, `raw_json: dict`, `latency_ms: float`, `provider: str`, `prompt_path: str`

- [ ] **Step 1: Write failing tests**

```python
# testing/tests/test_direct_mode.py
"""Tests for DirectModeService."""

import time
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest testing/tests/test_direct_mode.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement DirectModeService**

```python
# testing/services/direct_mode.py
"""Direct LLM mode — calls LLMService bypassing the dispatcher."""

import os
import time
from dataclasses import dataclass, field

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest testing/tests/test_direct_mode.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add testing/services/direct_mode.py testing/tests/test_direct_mode.py
git commit -m "feat: DirectModeService for LLM-only testing"
```

---

### Task 5: WebhookModeService

Service that simulates the full webhook flow using the extracted dispatcher.

**Files:**
- Create: `testing/services/webhook_mode.py`
- Create: `testing/tests/test_webhook_mode.py`

**Interfaces:**
- Consumes: `app.services.dispatcher.process_incoming_message(sender_phone, text_body, whatsapp_message_id) -> DispatchResult`, `app.services.llm.LLMService.reset_provider()`, `app.services.llm.LLMService.set_prompt_path(path)`, `testing.services.user_simulator.UserSimulator`
- Produces: `WebhookModeService` class with method `async def send_message(text: str, phone: str, provider: str, prompt_path: str) -> WebhookModeResult` where `WebhookModeResult` has `reply_text: str`, `raw_llm_response: dict | None`, `service_invoked: str | None`, `intent: str | None`, `latency_ms: float`, `provider: str`, `prompt_path: str`, `redis_state: dict | None`

- [ ] **Step 1: Write failing tests**

```python
# testing/tests/test_webhook_mode.py
"""Tests for WebhookModeService."""

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest testing/tests/test_webhook_mode.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement WebhookModeService**

```python
# testing/services/webhook_mode.py
"""Webhook mode — simulates the full dispatcher pipeline."""

import os
import time
from dataclasses import dataclass, field

from app.services.dispatcher import DispatchResult, process_incoming_message
from app.services.llm import LLMService
from app.services.conversation import ConversationService


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


class WebhookModeService:
    """Simulates the full webhook dispatch pipeline without HTTP."""

    async def send_message(
        self,
        text: str,
        phone: str,
        provider: str,
        prompt_path: str,
    ) -> WebhookModeResult:
        """
        Send a message through the full dispatcher pipeline.

        Configures the provider and prompt, invokes the dispatcher,
        captures Redis state, and measures latency.
        """
        os.environ["LLM_PROVIDER"] = provider
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
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest testing/tests/test_webhook_mode.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add testing/services/webhook_mode.py testing/tests/test_webhook_mode.py
git commit -m "feat: WebhookModeService for full dispatch testing"
```

---

### Task 6: Sidebar component

Streamlit sidebar with all configuration controls.

**Files:**
- Create: `testing/components/sidebar.py`
- Create: `testing/tests/test_sidebar_config.py`

**Interfaces:**
- Consumes: `testing.services.direct_mode.DirectModeService.get_available_providers() -> list[str]`, `testing.config.settings.TestingConfig`
- Produces: `render_sidebar() -> TestingConfig` (reads Streamlit widgets, returns updated config), `get_available_prompts() -> list[str]`

- [ ] **Step 1: Write failing tests for config logic (non-UI)**

```python
# testing/tests/test_sidebar_config.py
"""Tests for sidebar configuration logic (non-UI parts)."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from testing.components.sidebar import get_available_prompts, get_available_providers


class TestGetAvailableProviders:
    def test_returns_list_from_factory(self):
        providers = get_available_providers()
        assert isinstance(providers, list)
        assert "gemini" in providers
        assert "mistral" in providers

    def test_reflects_factory_changes(self):
        with patch(
            "testing.components.sidebar._PROVIDERS",
            {"gemini": object, "mistral": object, "openai": object},
        ):
            providers = get_available_providers()
        assert "openai" in providers


class TestGetAvailablePrompts:
    def test_includes_default_prompt(self, tmp_path):
        prompts = get_available_prompts(str(tmp_path))
        assert "prompt.md" in prompts

    def test_detects_custom_prompts(self, tmp_path):
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "prompt_v2.md").write_text("# V2 prompt")
        (prompts_dir / "prompt_conciso.md").write_text("# Conciso")
        (prompts_dir / "not_a_prompt.txt").write_text("ignored")

        prompts = get_available_prompts(str(tmp_path))
        assert "prompt.md" in prompts
        assert "prompt_v2.md" in prompts
        assert "prompt_conciso.md" in prompts
        assert "not_a_prompt.txt" not in prompts

    def test_handles_missing_prompts_dir(self, tmp_path):
        prompts = get_available_prompts(str(tmp_path / "nonexistent"))
        assert prompts == ["prompt.md"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest testing/tests/test_sidebar_config.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement sidebar.py**

```python
# testing/components/sidebar.py
"""Sidebar configuration panel for the testing environment."""

from pathlib import Path

import streamlit as st

from app.services.llm_providers.factory import _PROVIDERS
from testing.config.settings import TestingConfig


def get_available_providers() -> list[str]:
    """Return list of registered LLM provider names from the factory."""
    return list(_PROVIDERS.keys())


def get_available_prompts(testing_dir: str = "testing") -> list[str]:
    """
    Detect available prompt files.

    Always includes 'prompt.md' (project default).
    Scans testing/prompts/ for additional .md files.
    """
    prompts = ["prompt.md"]
    prompts_dir = Path(testing_dir) / "prompts"
    if prompts_dir.exists():
        for p in sorted(prompts_dir.glob("*.md")):
            prompts.append(p.name)
    return prompts


def render_sidebar() -> TestingConfig:
    """
    Render the sidebar and return the current configuration.

    Reads from st.session_state and Streamlit widgets.
    Returns an updated TestingConfig.
    """
    config = st.session_state.get("config", TestingConfig())

    with st.sidebar:
        st.header("🧪 Luka Testing")

        st.subheader("Modo")
        mode = st.radio(
            "Modo de operación",
            options=["direct", "webhook"],
            format_func=lambda x: "Directo (LLM)" if x == "direct" else "Webhook (completo)",
            index=0 if config.mode == "direct" else 1,
            key="mode_radio",
        )
        config.mode = mode

        st.subheader("Modelo LLM")
        providers = get_available_providers()
        provider_index = providers.index(config.provider) if config.provider in providers else 0
        provider = st.selectbox(
            "Provider",
            options=providers,
            index=provider_index,
            key="provider_select",
        )
        config.provider = provider

        st.subheader("Prompt")
        prompts = get_available_prompts()
        prompt_index = prompts.index(config.prompt_path) if config.prompt_path in prompts else 0
        prompt = st.selectbox(
            "Archivo de prompt",
            options=prompts,
            index=prompt_index,
            key="prompt_select",
        )
        config.prompt_path = prompt

        st.subheader("Usuario simulado")
        config.user_registered = st.checkbox(
            "Registrado",
            value=config.user_registered,
            key="user_registered_check",
        )
        config.phone = st.text_input(
            "Teléfono",
            value=config.phone,
            key="phone_input",
        )
        config.user_name = st.text_input(
            "Nombre",
            value=config.user_name,
            key="name_input",
        )

        st.subheader("Acciones")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🗑 Limpiar chat", key="clear_chat"):
                st.session_state.messages = []
                st.rerun()
        with col2:
            if st.button("🔄 Reset DB", key="reset_db"):
                st.session_state["reset_db_requested"] = True

        st.subheader("Debug")
        config.debug_json = st.checkbox("JSON crudo LLM", value=config.debug_json, key="debug_json")
        config.debug_latency = st.checkbox("Latencia", value=config.debug_latency, key="debug_latency")
        config.debug_redis = st.checkbox("Estado Redis", value=config.debug_redis, key="debug_redis")
        config.debug_logs = st.checkbox("Logs dispatcher", value=config.debug_logs, key="debug_logs")

    st.session_state.config = config
    return config
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest testing/tests/test_sidebar_config.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add testing/components/sidebar.py testing/tests/test_sidebar_config.py
git commit -m "feat: sidebar configuration panel with dynamic provider/prompt detection"
```

---

### Task 7: Debug panel component

Collapsible debug information rendered below each assistant message.

**Files:**
- Create: `testing/components/debug_panel.py`
- Create: `testing/tests/test_debug_panel.py`

**Interfaces:**
- Consumes: `debug_data: dict` (from `ChatMessage.debug`), `flags: dict` (from `TestingConfig.debug_*`)
- Produces: `render_debug(debug_data: dict, flags: dict) -> None` (renders Streamlit widgets), `format_debug_for_export(debug_data: dict) -> dict` (serializable dict for JSON export)

- [ ] **Step 1: Write failing tests**

```python
# testing/tests/test_debug_panel.py
"""Tests for debug panel formatting logic."""

import pytest

from testing.components.debug_panel import format_debug_for_export


class TestFormatDebugForExport:
    def test_includes_all_fields(self):
        debug_data = {
            "raw_json": {"intent": "expense", "amount": 5000},
            "latency_ms": 342.5,
            "service_log": "FinanceService.register_movement_with_category",
            "redis_state": {"step": "none"},
            "provider": "gemini",
            "prompt_used": "prompt.md",
        }
        exported = format_debug_for_export(debug_data)

        assert exported["raw_json"]["intent"] == "expense"
        assert exported["latency_ms"] == 342.5
        assert exported["service_log"] == "FinanceService.register_movement_with_category"
        assert exported["redis_state"]["step"] == "none"
        assert exported["provider"] == "gemini"

    def test_handles_missing_fields(self):
        debug_data = {"latency_ms": 100.0}
        exported = format_debug_for_export(debug_data)

        assert exported["latency_ms"] == 100.0
        assert exported.get("raw_json") is None
        assert exported.get("redis_state") is None

    def test_handles_empty_dict(self):
        exported = format_debug_for_export({})
        assert isinstance(exported, dict)

    def test_handles_none_values(self):
        debug_data = {
            "raw_json": None,
            "latency_ms": 0.0,
            "service_log": None,
            "redis_state": None,
        }
        exported = format_debug_for_export(debug_data)
        assert exported["raw_json"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest testing/tests/test_debug_panel.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement debug_panel.py**

```python
# testing/components/debug_panel.py
"""Debug panel — collapsible debug info per assistant message."""

import streamlit as st


def format_debug_for_export(debug_data: dict) -> dict:
    """
    Format debug data for JSON export.

    Ensures all fields are serializable. Missing fields become None.
    """
    return {
        "raw_json": debug_data.get("raw_json"),
        "latency_ms": debug_data.get("latency_ms"),
        "service_log": debug_data.get("service_log"),
        "redis_state": debug_data.get("redis_state"),
        "provider": debug_data.get("provider"),
        "prompt_used": debug_data.get("prompt_used"),
    }


def render_debug(debug_data: dict, flags: dict) -> None:
    """
    Render collapsible debug info below an assistant message.

    Only renders if at least one debug flag is active and there is data.
    """
    active_flags = any([
        flags.get("json"),
        flags.get("latency"),
        flags.get("redis"),
        flags.get("logs"),
    ])

    if not active_flags or not debug_data:
        return

    with st.expander("🔍 Debug", expanded=False):
        if flags.get("json") and debug_data.get("raw_json") is not None:
            st.subheader("JSON crudo LLM")
            st.json(debug_data["raw_json"])

        if flags.get("latency") and debug_data.get("latency_ms") is not None:
            st.metric("Latencia", f"{debug_data['latency_ms']:.0f}ms")

        if flags.get("logs") and debug_data.get("service_log"):
            st.subheader("Service invocado")
            st.code(debug_data["service_log"])

        if flags.get("redis") and debug_data.get("redis_state") is not None:
            st.subheader("Estado Redis")
            st.json(debug_data["redis_state"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest testing/tests/test_debug_panel.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add testing/components/debug_panel.py testing/tests/test_debug_panel.py
git commit -m "feat: debug panel with collapsible LLM/Redis/latency info"
```

---

### Task 8: Chat component + export

Chat message rendering, input handling, session state, and export functionality.

**Files:**
- Create: `testing/components/chat.py`
- Create: `testing/tests/test_chat_state.py`

**Interfaces:**
- Consumes: `testing.services.direct_mode.DirectModeService`, `testing.services.webhook_mode.WebhookModeService`, `testing.config.settings.TestingConfig`, `testing.config.settings.ChatMessage`, `testing.components.debug_panel.render_debug`, `testing.components.debug_panel.format_debug_for_export`
- Produces: `render_chat(config: TestingConfig) -> None` (renders Streamlit chat), `export_as_json(messages: list[dict]) -> str`, `export_as_text(messages: list[dict]) -> str`

- [ ] **Step 1: Write failing tests**

```python
# testing/tests/test_chat_state.py
"""Tests for chat state management and export logic."""

import json

import pytest

from testing.components.chat import export_as_json, export_as_text


class TestExportAsJson:
    def test_exports_valid_json(self):
        messages = [
            {"role": "user", "content": "hola", "debug": {}},
            {
                "role": "assistant",
                "content": "¡Hola!",
                "debug": {
                    "raw_json": {"intent": "greeting"},
                    "latency_ms": 42.0,
                },
            },
        ]
        result = export_as_json(messages)
        parsed = json.loads(result)

        assert len(parsed) == 2
        assert parsed[0]["role"] == "user"
        assert parsed[1]["debug"]["raw_json"]["intent"] == "greeting"

    def test_exports_empty_list(self):
        result = export_as_json([])
        assert json.loads(result) == []

    def test_handles_special_characters(self):
        messages = [
            {"role": "user", "content": "Gasté $5.000 en \"super\"", "debug": {}},
        ]
        result = export_as_json(messages)
        parsed = json.loads(result)
        assert "$5.000" in parsed[0]["content"]


class TestExportAsText:
    def test_formats_readable_conversation(self):
        messages = [
            {"role": "user", "content": "Gasté 5000 en super", "debug": {}},
            {"role": "assistant", "content": "✅ Registrado.", "debug": {}},
        ]
        result = export_as_text(messages)

        assert "Usuario: Gasté 5000 en super" in result
        assert "Luka: ✅ Registrado." in result

    def test_exports_empty_list(self):
        result = export_as_text([])
        assert result == ""

    def test_excludes_debug_data(self):
        messages = [
            {
                "role": "assistant",
                "content": "ok",
                "debug": {"raw_json": {"intent": "greeting"}, "latency_ms": 42.0},
            },
        ]
        result = export_as_text(messages)
        assert "intent" not in result
        assert "latency" not in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest testing/tests/test_chat_state.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement chat.py**

```python
# testing/components/chat.py
"""Chat component — message rendering, input, and export."""

import asyncio
import json

import streamlit as st

from testing.components.debug_panel import render_debug
from testing.config.settings import TestingConfig
from testing.services.direct_mode import DirectModeService
from testing.services.webhook_mode import WebhookModeService


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
    Route message to the appropriate service based on mode.

    Returns (reply_text, debug_data).
    """
    if config.mode == "direct":
        service = DirectModeService()
        result = await service.send_message(
            text=text,
            provider=config.provider,
            prompt_path=_get_prompt_path(config),
        )
        debug_data = {
            "raw_json": result.raw_json,
            "latency_ms": result.latency_ms,
            "service_log": "DirectModeService (LLM only)",
            "redis_state": None,
            "provider": result.provider,
            "prompt_used": result.prompt_path,
        }
        return result.reply_text, debug_data
    else:
        service = WebhookModeService()
        result = await service.send_message(
            text=text,
            phone=config.phone,
            provider=config.provider,
            prompt_path=_get_prompt_path(config),
        )
        debug_data = {
            "raw_json": result.raw_llm_response,
            "latency_ms": result.latency_ms,
            "service_log": result.service_invoked or "unknown",
            "redis_state": result.redis_state,
            "provider": result.provider,
            "prompt_used": result.prompt_path,
        }
        return result.reply_text, debug_data


def render_chat(config: TestingConfig) -> None:
    """Render the chat interface and handle user input."""

    # Display existing messages
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            if msg["role"] == "assistant" and msg.get("debug"):
                flags = {
                    "json": config.debug_json,
                    "latency": config.debug_latency,
                    "redis": config.debug_redis,
                    "logs": config.debug_logs,
                }
                render_debug(msg["debug"], flags)

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
        with st.chat_message("assistant"):
            with st.spinner("Procesando..."):
                reply_text, debug_data = asyncio.run(
                    _process_message(prompt, config)
                )

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest testing/tests/test_chat_state.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add testing/components/chat.py testing/tests/test_chat_state.py
git commit -m "feat: chat component with message rendering and export"
```

---

### Task 9: Wire everything together in app.py

Assemble all components into the final Streamlit application.

**Files:**
- Modify: `testing/app.py` (replace placeholder with full implementation)

**Interfaces:**
- Consumes: `testing.components.sidebar.render_sidebar() -> TestingConfig`, `testing.components.chat.render_chat(config)`, `testing.services.user_simulator.UserSimulator`
- Produces: Complete Streamlit application

- [ ] **Step 1: Implement full app.py**

```python
# testing/app.py
"""Luka Testing Environment — Streamlit entry point."""

import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from testing.config.settings import TestingConfig
from testing.components.sidebar import render_sidebar
from testing.components.chat import render_chat
from testing.services.user_simulator import UserSimulator

st.set_page_config(
    page_title="Luka Testing",
    page_icon="🧪",
    layout="wide",
)

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "config" not in st.session_state:
    st.session_state.config = TestingConfig()
if "user_simulator_initialized" not in st.session_state:
    st.session_state.user_simulator_initialized = False

# Render sidebar and get config
config = render_sidebar()

# Handle user simulation setup
if config.mode == "webhook" and config.user_registered:
    if not st.session_state.user_simulator_initialized or st.session_state.get("reset_db_requested"):
        from app.models.database import SessionLocal
        sim = UserSimulator(SessionLocal)
        sim.create_test_user(config.phone, config.user_name)
        st.session_state.user_simulator_initialized = True
        st.session_state.pop("reset_db_requested", None)

# Handle DB reset
if st.session_state.get("reset_db_requested"):
    from app.models.database import SessionLocal
    sim = UserSimulator(SessionLocal)
    sim.reset_user_data(config.phone)
    st.session_state.user_simulator_initialized = False
    st.session_state.pop("reset_db_requested", None)
    st.toast("Base de datos reseteada")

# Render chat
render_chat(config)
```

- [ ] **Step 2: Build and test Docker**

Run:
```bash
docker compose -f testing/docker-compose.yml build
docker compose -f testing/docker-compose.yml up -d
```
Expected: Full app accessible at `http://localhost:8501` with sidebar, chat input, mode selection.

- [ ] **Step 3: Manual smoke test**

Verify in browser:
1. Sidebar shows all controls (mode, provider, prompt, user, debug toggles)
2. Provider dropdown shows "gemini" and "mistral"
3. Mode toggle switches between "Directo" and "Webhook"
4. Chat input accepts text
5. Export buttons appear after first message (requires API key for LLM response)

- [ ] **Step 4: Run all tests**

Run:
```bash
python -m pytest -v
python -m pytest testing/tests/ -v
python -m ruff check .
```
Expected: All PASS, no lint errors

- [ ] **Step 5: Commit**

```bash
git add testing/app.py
git commit -m "feat: assemble complete Streamlit testing environment

Wires sidebar, chat, debug panel, user simulator, and both operation
modes into the final app. Docker Compose ready."
```

- [ ] **Step 6: Stop Docker**

Run:
```bash
docker compose -f testing/docker-compose.yml down
```
