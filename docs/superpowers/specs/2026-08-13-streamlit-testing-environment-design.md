# Streamlit Testing Environment — Design Spec

**Date:** 2026-08-13
**Status:** Approved (brainstorming complete)

## Goal

Entorno de testing interactivo basado en Streamlit para que el equipo de desarrollo pruebe funcionalidades del asistente Luka mediante un chat. Ejecutado vía Docker para garantizar compatibilidad entre entornos.

## Architecture

Aplicación Streamlit que importa directamente los services de `app/` (LLMService, FinanceService, etc.) sin API intermedia. Dos modos de operación: directo (LLM only) y webhook (flujo completo). Docker Compose con dos servicios: Streamlit + Redis.

## Location

Carpeta `testing/` en raíz del repo. Completamente separada del Dockerfile de producción.

---

## Modos de operación

### Modo Directo (LLM)
- Llama `LLMService.process_message(text)` directamente
- Sin onboarding, sin dispatcher, sin persistencia
- Para probar: respuestas LLM, parsing de intents, comparación entre providers, A/B testing de prompts

### Modo Webhook (flujo completo)
- Simula el flujo completo del webhook sin HTTP real
- Invoca la lógica del dispatcher internamente
- Para probar: onboarding, registro de movimientos, multi-turno, estado Redis, interacción entre services
- Requiere refactor: extraer función `process_incoming_message()` de `main.py`

## User Simulator
- Configurable desde sidebar: toggle para simular usuario registrado o no
- CRUD: crear usuario test, borrar, reset datos, seed categorías
- SQLite embebida en contenedor

## Panel Lateral (Sidebar)

Configuraciones:
- **Modo**: Directo (LLM) / Webhook (completo)
- **Modelo LLM**: dropdown dinámico desde `factory.py` (auto-detecta providers nuevos)
- **Prompt**: selector de archivos `.md` — default `prompt.md` + alternativas en `testing/prompts/`
- **Usuario simulado**: toggle registrado/no, teléfono, nombre
- **Acciones**: limpiar chat, reset DB, exportar historial
- **Debug toggles**: JSON crudo LLM, latencia, estado Redis, logs dispatcher

## Chat

- Layout principal (~75% ancho)
- `st.chat_message` nativo de Streamlit
- Estado en `st.session_state` (mensajes + config)
- Debug info colapsable (`st.expander`) debajo de cada respuesta del asistente

## Features adicionales

- **Historial exportable**: JSON (con debug data) y texto (solo conversación)
- **JSON crudo LLM**: intent, amount, category, etc.
- **Métricas latencia**: ms por request
- **Estado Redis**: conversation state en tiempo real
- **Logs dispatcher**: qué service se invocó, resultado
- **Selector de prompt**: A/B testing con prompts alternativos

## Docker Setup

```yaml
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
    depends_on:
      - redis

  redis:
    image: redis:7-alpine
    ports:
      - "6380:6379"
```

- DB: SQLite embebida (se crea limpia al iniciar)
- Sin autenticación (solo uso local)
- Puerto Redis 6380 para no chocar con Redis local

## Refactor requerido

Extraer lógica del dispatcher de `main.py` (~900 líneas) a función/service reutilizable. Tanto el webhook real como el modo testing invocan la misma lógica. Tests existentes deben seguir pasando + tests nuevos para el dispatcher extraído con coverage completa y edge cases.

## Testing (TDD/SDD)

| Capa | Qué se testea | Cómo |
|------|---------------|------|
| DirectModeService | LLM correcto, latencia, errores provider | Mock LLMService |
| WebhookModeService | Flujo completo, dispatch por intent, persistencia | Mock LLM + SQLite in-memory |
| UserSimulator | CRUD usuario, seed datos, cleanup | SQLite in-memory |
| Sidebar | Providers dinámicos, prompts detectados, config state | Mock factory + filesystem |
| Chat | Mensajes acumulados, debug show/hide, export | Mock session_state |
| Debug panel | Render condicional por flags, formatos | Mock data |
| Dispatcher (refactor) | Todos intents, edge cases, errores, multi-turno | Tests existentes + nuevos |

Edge cases clave:
- Provider inexistente
- LLM JSON malformado
- Redis no disponible en modo webhook
- Usuario no registrado + modo webhook sin simulación
- Prompt file no existe
- Timeout / latencia extrema
- Mensajes vacíos / solo espacios
- Cambio de provider mid-conversación

## File Structure

```
testing/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── app.py
├── config/
│   ├── __init__.py
│   └── settings.py
├── services/
│   ├── __init__.py
│   ├── direct_mode.py
│   ├── webhook_mode.py
│   └── user_simulator.py
├── components/
│   ├── __init__.py
│   ├── sidebar.py
│   ├── chat.py
│   └── debug_panel.py
├── prompts/
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_direct_mode.py
    ├── test_webhook_mode.py
    ├── test_user_simulator.py
    ├── test_sidebar_config.py
    ├── test_chat_state.py
    └── test_debug_panel.py
```
