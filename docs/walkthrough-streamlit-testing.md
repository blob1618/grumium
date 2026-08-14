# Luka Testing Environment — Walkthrough

Entorno de testing interactivo basado en Streamlit para probar el asistente financiero Luka por chat. Ejecutado vía Podman/Docker Compose (Streamlit + Redis), con tema oscuro tipo obsidiana y los logos de Luka integrados.

---

## Cambios totales implementados

### 1. Refactor: dispatcher extraído de `main.py`

**Nuevo:** `app/services/dispatcher.py`
- Extrae toda la lógica de dispatch del webhook de `main.py` (~500 líneas de helpers y handlers).
- Expone `process_incoming_message(sender_phone, text_body, whatsapp_message_id) -> DispatchResult`.
- `DispatchResult` transporta `reply_text`, `raw_llm_response`, `service_invoked`, `intent` y `debug_info`.
- Pipeline completo: onboarding → `/link` → `_update_ultimo_mensaje` → multi-turn (rename / reminder data) → LLM → dispatch por intent (movimientos, recordatorios, categorías) → fallback legacy.

**Modificado:** `app/main.py`
- De ~950 líneas a ~120. `handle_webhook` ahora solo parsea el payload y llama a `process_incoming_message`, enviando `reply_text` vía `send_whatsapp_message`.

**Tests movidos/actualizados:** `tests/test_webhook.py`, `tests/test_webhook_integration.py`, `tests/test_reminder.py` ahora mockean paths de `app.services.dispatcher.*`.

### 2. Entorno Streamlit en `testing/`

| Archivo | Responsabilidad |
|---|---|
| `Dockerfile` | Python 3.11-slim + Streamlit |
| `docker-compose.yml` | Servicios streamlit (8501) + redis (6380) |
| `requirements.txt` | `-r ../requirements.txt` + `streamlit` |
| `streamlit_app.py` | Entry point; inicializa SQLite aislada, estado, sidebar, chat, user simulator, tema obsidiana |
| `config/settings.py` | Dataclasses `TestingConfig` y `ChatMessage` |
| `services/webhook_mode.py` | `WebhookModeService` — simula el flujo completo vía dispatcher |
| `services/user_simulator.py` | `UserSimulator` — CRUD de usuarios de test + seed de categorías |
| `components/sidebar.py` | Panel lateral: provider, prompt, usuario, debug, logo-texto |
| `components/chat.py` | Render de chat, input, export JSON/texto, avatar del bot con logo |
| `components/debug_panel.py` | Expander colapsable con JSON crudo, latencia, Redis, service |
| `.streamlit/config.toml` | Tema obsidiana (dark) |
| `prompts/.gitkeep` | Directorio para prompts de A/B testing |

### 3. Imágenes (pedido del usuario)

- `public/logo-luka-texto.png` → **arriba del panel lateral** (`sidebar.py`).
- `public/logo-luka.png` → **avatar del bot** en el chat (`chat.py`).
- Paleta **obsidiana**: `#0d1117` fondo, `#161b22` sidebar, `#21262d` secundario, `#e6edf3` texto, `#8ab4f8` acento.

### 4. `.dockerignore` (raíz)

Excluye `.venv/`, `.git/`, caches y artefactos del contexto de build. Acelera drásticamente el build de Podman/Docker (el `.venv` pesa ~478 MB) y aplica también al Dockerfile de producción.

### 5. Tests y cobertura

- **Dispatcher: 100% de cobertura** (`app/services/dispatcher.py`, 425 statements).
  - `tests/test_dispatcher.py` — intents, onboarding, `/link`, multi-turno, legacy branch, edge cases (~60 tests).
  - `tests/test_dispatcher_helpers.py` — tests unitarios de las reply/format helpers (~75 tests).
- **Paquete `testing/`: 100% de cobertura** (services, components, config).
  - 7 archivos de test + `conftest.py` (SQLite in-memory).
  - `test_components_ui.py` mockea el módulo `streamlit` para cubrir el render.
- **Suite completa del repo: 445 passed.**

### 6. Artefactos Playwright

Las capturas de validación quedan en `artifacts/`, incluyendo:

- `streamlit-import-error-before-fix.png` — error original de shadowing de `app`.
- `scenario-webhook-no-table-before-fix.png` — error original de SQLite sin tablas.
- `streamlit-after-fix-loading.png` — carga inicial correcta.
- `scenario-webhook-unregistered-invitation-success.png` — invitación de usuario no registrado.
- `scenario-webhook-registered-expense-success.png` — persistencia de movimiento.
- `scenario-reset-db-data-cleared-success.png` — reset verificado contra SQLite.
- `scenario-mobile-layout-success.png` — layout móvil.

---

## Guía de ejecución paso a paso

### Requisitos

- Podman (o Docker) con máquina iniciada.
- Python 3.11+ si se quiere correr sin contenedores.

### Opción A: con Podman/Docker (recomendada)

```powershell
# 1. Asegurarse de que la máquina Podman esté corriendo
podman machine list
podman machine start podman-machine   # si está apagada

# 2. Construir imagen Compose (el primer build baja python:3.11-slim + instala deps)
podman compose -f testing/docker-compose.yml build

# 3. Levantar la stack (Streamlit + Redis)
podman compose -f testing/docker-compose.yml up -d

# 4. Abrir en el navegador
#    http://localhost:8501

# 5. Verificar salud
Invoke-WebRequest http://localhost:8501/_stcore/health   # → ok

# 6. Bajar la stack cuando se termine
podman compose -f testing/docker-compose.yml down
```

> Nota: `docker compose` funciona igual si tenés Docker en vez de Podman.

### Opción B: local, sin contenedores

```powershell
# 1. Crear/activar venv e instalar deps
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r testing/requirements.txt

# 2. Copiar env si no existe
Copy-Item .env.example .env   # ajustar LLM_API_KEY / GEMINI_API_KEY

# 3. Correr Streamlit
streamlit run testing/streamlit_app.py --server.port=8501

# 4. Abrir http://localhost:8501
```

### Cómo usar la app

1. **Chat**: cada mensaje recorre el flujo completo del dispatcher (onboarding, persistencia, multi-turno) vía `WebhookModeService`, igual que un webhook real de WhatsApp.
2. **Modelo LLM**: dropdown con los providers de `factory.py` (`gemini`, `mistral`).
3. **Prompt**: selector de `prompt.md` o de archivos `.md` en `testing/prompts/` (para A/B testing).
4. **Usuario simulado**: toggle registrado/no, teléfono y nombre. Con usuario registrado se crea el usuario en la BD automáticamente.
5. **Debug**: expander `🔍 Debug` bajo cada respuesta con JSON crudo del LLM, latencia, estado Redis y service invocado. Toggles en el sidebar.
6. **Exportar**: botones JSON (con debug) y Texto (solo conversación) tras el primer mensaje.
7. **Acciones**: limpiar chat y resetear la BD de test.

---

## Validación (tests y lint)

```powershell
# Lint
python -m ruff check .

# Tests del entorno + dispatcher (rápidos)
python -m pytest tests/test_dispatcher.py tests/test_dispatcher_helpers.py testing/tests/ -v

# Suite completa del repo
python -m pytest -v

# Cobertura
python -m pytest tests/test_dispatcher.py tests/test_dispatcher_helpers.py testing/tests/ --cov=app.services.dispatcher --cov=testing --cov-report=term-missing
```

Resultados esperados:

| Scope | Resultado |
|---|---|
| Dispatcher (`app/services/dispatcher.py`) | 100% |
| Paquete `testing/` | 100% |
| Suite completa | 444 passed |
| Ruff | 0 errores |
