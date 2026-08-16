# Fix formato WhatsApp en el chat del entorno de testing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hacer que los mensajes del asistente en el chat de Streamlit respeten los saltos de línea (`\n`) y la negrita (`*texto*`) de WhatsApp, tal como se ven en la app real.

**Architecture:** El bug es solo de visualización: `testing/components/chat.py` renderiza con `st.write()`, que interpreta el texto como Markdown, donde un `\n` simple no produce salto de línea y `*texto*` es itálica. Se agrega una función pura `whatsapp_to_markdown()` que convierte el formato WhatsApp a Markdown (hard breaks + negrita) y una función `render_assistant_text()` que la usa con `st.markdown()`. No se toca `app/` ni el pipeline del dispatcher.

**Tech Stack:** Python 3.11, Streamlit, pytest, pytest-cov, ruff.

## Global Constraints

- **TDD estricto:** en cada tarea se escribe primero el test, se verifica que falla, y recién después se escribe la implementación.
- **Cobertura 100%:** el módulo tocado `testing/components/chat.py` y el paquete `testing` completo deben quedar en 100% (`--cov-fail-under=100`).
- **Alcance:** solo se modifica `testing/components/chat.py` y tests en `testing/tests/`. No tocar `app/`, `prompt.md`, ni `requirements.txt`.
- **Lint:** `ruff check .` debe pasar sin errores.
- **Commits:** Conventional Commits, un commit por tarea.

---

### Task 1: Función pura `whatsapp_to_markdown`

**Files:**
- Create: `testing/tests/test_chat_formatting.py`
- Modify: `testing/components/chat.py` (agregar `import re` y las dos funciones de transformación)

**Interfaces:**
- Produces: `whatsapp_to_markdown(text: str) -> str` — convierte `\n` → `"  \n"` (hard break de CommonMark) y `*texto*` → `**texto**` (negrita Markdown). No modifica asteriscos sueltos ni texto plano.

- [ ] **Step 1: Escribir el test que falla**

Crear `testing/tests/test_chat_formatting.py`:

```python
"""Tests for WhatsApp-to-Markdown rendering helpers in the chat component."""

from testing.components.chat import whatsapp_to_markdown


class TestWhatsappToMarkdown:
    def test_plain_text_unchanged(self):
        assert whatsapp_to_markdown("hola") == "hola"

    def test_single_newline_becomes_hard_break(self):
        assert whatsapp_to_markdown("l1\nl2") == "l1  \nl2"

    def test_double_newline_keeps_blank_line(self):
        assert whatsapp_to_markdown("a\n\nb") == "a  \n  \nb"

    def test_whatsapp_bold_becomes_markdown_bold(self):
        assert whatsapp_to_markdown("*hola*") == "**hola**"

    def test_multiple_bold_pairs_converted(self):
        assert whatsapp_to_markdown("*a* y *b*") == "**a** y **b**"

    def test_lone_asterisk_left_alone(self):
        assert whatsapp_to_markdown("5 * 3") == "5 * 3"

    def test_empty_string(self):
        assert whatsapp_to_markdown("") == ""
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `.venv/bin/python -m pytest -v testing/tests/test_chat_formatting.py`
Expected: FAIL con `ImportError: cannot import name 'whatsapp_to_markdown' from 'testing.components.chat'`

- [ ] **Step 3: Escribir la implementación mínima**

En `testing/components/chat.py`, agregar `import re` al bloque de imports (después de `import json`):

```python
import re
```

Insertar las siguientes funciones después de `export_as_text` (línea 40) y antes de `_get_prompt_path`:

```python
_WHATSAPP_BOLD = re.compile(r"\*([^*\n]+)\*")


def whatsapp_to_markdown(text: str) -> str:
    """Convierte formato WhatsApp (`\\n`, `*negrita*`) a Markdown de Streamlit."""
    with_hard_breaks = text.replace("\n", "  \n")
    return _WHATSAPP_BOLD.sub(r"**\1**", with_hard_breaks)
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `.venv/bin/python -m pytest -v testing/tests/test_chat_formatting.py`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add testing/tests/test_chat_formatting.py testing/components/chat.py
git commit -m "feat(testing): convertir formato WhatsApp a Markdown para el chat"
```

---

### Task 2: Render `render_assistant_text` con `st.markdown`

**Files:**
- Modify: `testing/tests/test_chat_formatting.py`
- Modify: `testing/components/chat.py` (agregar `render_assistant_text`)

**Interfaces:**
- Consumes: `whatsapp_to_markdown(text: str) -> str` (Task 1)
- Produces: `render_assistant_text(text: str) -> None` — renderiza con `st.markdown()` el texto ya transformado.

- [ ] **Step 1: Escribir el test que falla**

Agregar a `testing/tests/test_chat_formatting.py` (el patch de `st` se define inline, igual que hace el fixture `mock_st` de `test_components_ui.py`, que no es compartido entre módulos):

```python
from unittest.mock import patch


class TestRenderAssistantText:
    def test_renders_markdown_with_transformed_text(self):
        with patch("testing.components.chat.st") as chat_st:
            from testing.components.chat import render_assistant_text

            render_assistant_text("📌 *Tus categorías:*\n• comida")

        chat_st.markdown.assert_called_once_with(
            "📌 **Tus categorías:**  \n• comida"
        )

    def test_renders_fallback_text_when_empty(self):
        with patch("testing.components.chat.st") as chat_st:
            from testing.components.chat import render_assistant_text

            render_assistant_text("")

        chat_st.markdown.assert_called_once_with("")
```

Nota: el import de `render_assistant_text` va dentro del `with` porque `chat.py` tiene `import streamlit as st` a nivel módulo y el patch debe estar activo al momento del import en entornos sin streamlit.

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `.venv/bin/python -m pytest -v testing/tests/test_chat_formatting.py -k TestRenderAssistantText`
Expected: FAIL con `ImportError: cannot import name 'render_assistant_text' from 'testing.components.chat'`

- [ ] **Step 3: Escribir la implementación mínima**

En `testing/components/chat.py`, justo después de `whatsapp_to_markdown`:

```python
def render_assistant_text(text: str) -> None:
    """Renderiza el texto del asistente respetando saltos de línea y negrita."""
    st.markdown(whatsapp_to_markdown(text))
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `.venv/bin/python -m pytest -v testing/tests/test_chat_formatting.py`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add testing/tests/test_chat_formatting.py testing/components/chat.py
git commit -m "feat(testing): renderizar texto del asistente con st.markdown"
```

---

### Task 3: Integrar el renderer en `render_chat`

**Files:**
- Modify: `testing/tests/test_components_ui.py` (agregar tests de integración)
- Modify: `testing/components/chat.py:83,118` (reemplazar `st.write` por `render_assistant_text` en los mensajes del asistente)

**Interfaces:**
- Consumes: `render_assistant_text(text: str) -> None` (Task 2)
- Los mensajes del **usuario** (líneas 94 y 105) siguen con `st.write`.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a la clase `TestRenderChat` de `testing/tests/test_components_ui.py`:

```python
    def test_render_chat_assistant_history_uses_markdown_renderer(self, mock_st):
        from testing.components.chat import render_chat

        chat_st = mock_st["chat"]
        chat_st.session_state.messages = [
            {"role": "assistant", "content": "l1\nl2", "debug": {}},
        ]
        chat_st.chat_input.return_value = None

        chat_msg = MagicMock()
        chat_msg.__enter__ = MagicMock(return_value=None)
        chat_msg.__exit__ = MagicMock(return_value=False)
        chat_st.chat_message.return_value = chat_msg

        render_chat(TestingConfig())

        chat_st.markdown.assert_called_once_with("l1  \nl2")
        chat_st.write.assert_not_called()

    def test_render_chat_new_assistant_reply_uses_markdown_renderer(self, mock_st):
        from testing.components.chat import render_chat

        chat_st = mock_st["chat"]
        chat_st.session_state.messages = []
        chat_st.chat_input.return_value = "hola"
        chat_st.chat_message.return_value.__enter__ = MagicMock(return_value=None)
        chat_st.chat_message.return_value.__exit__ = MagicMock(return_value=False)
        chat_st.spinner.return_value.__enter__ = MagicMock(return_value=None)
        chat_st.spinner.return_value.__exit__ = MagicMock(return_value=False)
        chat_st.sidebar.__enter__ = MagicMock(return_value=None)
        chat_st.sidebar.__exit__ = MagicMock(return_value=False)
        chat_st.download_button.return_value = None

        with (
            patch(
                "testing.components.chat._process_message",
                new_callable=AsyncMock,
                return_value=("l1\nl2", {"latency_ms": 1.0}),
            ),
        ):
            render_chat(TestingConfig())

        chat_st.markdown.assert_called_once_with("l1  \nl2")

    def test_render_chat_user_message_still_uses_write(self, mock_st):
        from testing.components.chat import render_chat

        chat_st = mock_st["chat"]
        chat_st.session_state.messages = [
            {"role": "user", "content": "hola", "debug": {}},
        ]
        chat_st.chat_input.return_value = None

        chat_msg = MagicMock()
        chat_msg.__enter__ = MagicMock(return_value=None)
        chat_msg.__exit__ = MagicMock(return_value=False)
        chat_st.chat_message.return_value = chat_msg

        render_chat(TestingConfig())

        chat_st.write.assert_called_once_with("hola")
        chat_st.markdown.assert_not_called()
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `.venv/bin/python -m pytest -v testing/tests/test_components_ui.py::TestRenderChat -k markdown_renderer`
Expected: FAIL — `chat_st.markdown` nunca se llama porque `render_chat` aún usa `st.write`.

- [ ] **Step 3: Escribir la implementación mínima**

En `testing/components/chat.py`, dentro de `render_chat`:

Reemplazar la línea 83:

```python
            with st.chat_message("assistant", avatar=bot_avatar()):
                st.write(msg["content"])
```

por:

```python
            with st.chat_message("assistant", avatar=bot_avatar()):
                render_assistant_text(msg["content"])
```

Reemplazar la línea 118:

```python
            else:
                st.write(reply_text or "Sin respuesta")
```

por:

```python
            else:
                render_assistant_text(reply_text or "Sin respuesta")
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `.venv/bin/python -m pytest -v testing/tests/test_components_ui.py testing/tests/test_chat_formatting.py`
Expected: PASS (todos, incluidos los tests preexistentes de `render_chat`)

- [ ] **Step 5: Commit**

```bash
git add testing/tests/test_components_ui.py testing/components/chat.py
git commit -m "fix(testing): respetar saltos de línea y negrita en el chat"
```

---

### Task 4: Cobertura 100% del paquete `testing`

El paquete `testing` está en 99% por una línea sin cubrir en `testing/tests/test_streamlit_app.py:54` (la rama `else` del restore de `DATABASE_URL` en `_import_app`). Para que el gate `--cov=testing --cov-fail-under=100` pase completo, se agrega un test.

**Files:**
- Modify: `testing/tests/test_streamlit_app.py` (agregar test)

- [ ] **Step 1: Escribir el test de cobertura (rama `else` del restore de `DATABASE_URL`)**

Agregar a la clase `TestStreamlitAppEntrypoint`:

```python
    def test_import_restores_existing_database_url(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://prod/db")
        _, _, mock_chat, mock_user_sim, _ = _import_app()

        assert os.environ["DATABASE_URL"] == "postgresql://prod/db"
        mock_user_sim.create_test_user.assert_called_once()
```

- [ ] **Step 2: Correr el test y verificar que pasa**

Run: `.venv/bin/python -m pytest -v testing/tests/test_streamlit_app.py`
Expected: PASS (7 passed). El test es puro (solo cubre una rama del helper `_import_app` que ya existe; no hay código productivo que cambiar).

- [ ] **Step 3: Verificar cobertura del paquete completo**

Run: `WHATSAPP_VERIFY_TOKEN=test_verify_token .venv/bin/python -m pytest -q testing/tests --cov=testing --cov-report=term-missing --cov-fail-under=100`
Expected: PASS — `testing/components/chat.py` y el TOTAL en 100%.

- [ ] **Step 4: Commit**

```bash
git add testing/tests/test_streamlit_app.py
git commit -m "test(testing): cubrir restauración de DATABASE_URL en _import_app"
```

---

### Task 5: Verificación final y gates

**Files:** ninguno (solo comandos de verificación).

- [ ] **Step 1: Suite completa del entorno de testing**

Run: `WHATSAPP_VERIFY_TOKEN=test_verify_token .venv/bin/python -m pytest -v testing/tests`
Expected: todos PASS (80 tests: 67 preexistentes + 9 en `test_chat_formatting.py` + 3 en `test_components_ui.py` + 1 en `test_streamlit_app.py`).

- [ ] **Step 2: Gate de cobertura 100% del módulo tocado**

Run: `WHATSAPP_VERIFY_TOKEN=test_verify_token .venv/bin/python -m pytest -q testing/tests --cov=testing.components.chat --cov-report=term-missing --cov-fail-under=100`
Expected: PASS — 100% en `testing/components/chat.py`.

- [ ] **Step 3: Gate de cobertura 100% del paquete testing**

Run: `WHATSAPP_VERIFY_TOKEN=test_verify_token .venv/bin/python -m pytest -q testing/tests --cov=testing --cov-report=term-missing --cov-fail-under=100`
Expected: PASS — TOTAL 100%.

- [ ] **Step 4: Suite raíz intacta**

Run: `WHATSAPP_VERIFY_TOKEN=test_verify_token .venv/bin/python -m pytest -v`
Expected: todos PASS (no se tocó `app/` ni `tests/`).

- [ ] **Step 5: Lint**

Run: `.venv/bin/python -m ruff check .`
Expected: `All checks passed!`

- [ ] **Step 6 (opcional): Verificación visual con Docker**

```bash
docker compose -f testing/docker-compose.yml up -d
```

Abrir `http://localhost:8501`, escribir "mostrame mis categorías" o "qué recordatorios tengo" con el usuario registrado y verificar que los bullets se muestran uno por línea y los títulos en negrita.

```bash
docker compose -f testing/docker-compose.yml down
```
