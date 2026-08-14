"""Tests del GeminiProvider sobre el driver común de retry/fallback."""

import json
from contextlib import asynccontextmanager
from unittest.mock import patch

import httpx
import pytest

from app.services.llm_providers.gemini import GeminiProvider
from tests.provider_fakes import FakeAsyncClient, FakeResponse

VALID_JSON = '{"intent": "expense", "amount": 5000}'


@asynccontextmanager
async def _run_generate(responses, model="gemini-3.1-flash-lite"):
    provider = GeminiProvider()
    client = FakeAsyncClient(responses)
    with (
        patch.dict("os.environ", {"GEMINI_API_KEY": "test-key", "GEMINI_MODEL": model}, clear=False),
        patch("app.services.llm_providers.gemini.httpx.AsyncClient", lambda **kw: client),
    ):
        yield provider, client


@pytest.mark.asyncio
async def test_503_se_reintenta_y_luego_retorna_ok():
    async with _run_generate([FakeResponse(503), FakeResponse(200, text=VALID_JSON)]) as (provider, client):
        result = await provider.generate_json("sys", "user")
    assert result["intent"] == "expense"
    assert len(client.requested_urls) == 2


@pytest.mark.asyncio
async def test_503_repetido_cae_al_modelo_fallback():
    async with _run_generate(
        [FakeResponse(503), FakeResponse(503), FakeResponse(200, text=VALID_JSON)]
    ) as (provider, client):
        result = await provider.generate_json("sys", "user")
    assert result["intent"] == "expense"
    urls = client.requested_urls
    assert any("gemini-3.1-flash-lite" in u for u in urls)
    assert any("gemini-3.5-flash" in u for u in urls)


@pytest.mark.asyncio
async def test_503_en_todos_los_modelos_expone_el_error_real():
    async with _run_generate([FakeResponse(503)] * 6) as (provider, client):  # 2 reintentos x 3 modelos
        with pytest.raises(httpx.HTTPStatusError):
            await provider.generate_json("sys", "user")


@pytest.mark.asyncio
async def test_429_se_reintenta_sin_cambiar_de_modelo():
    async with _run_generate(
        [FakeResponse(429, headers={"Retry-After": "0"}), FakeResponse(200, text=VALID_JSON)]
    ) as (provider, client):
        result = await provider.generate_json("sys", "user")
    assert result["intent"] == "expense"
    assert all("gemini-3.1-flash-lite" in u for u in client.requested_urls)


@pytest.mark.asyncio
async def test_404_cambia_inmediatamente_al_siguiente_modelo():
    async with _run_generate([FakeResponse(404), FakeResponse(200, text=VALID_JSON)]) as (provider, client):
        result = await provider.generate_json("sys", "user")
    assert result["intent"] == "expense"
    assert client.requested_urls[-1].endswith("gemini-3.5-flash:generateContent")


@pytest.mark.asyncio
async def test_json_invalido_expone_el_error_de_parseo():
    async with _run_generate([FakeResponse(200, text="esto no es json")]) as (provider, client):
        with pytest.raises(json.JSONDecodeError):
            await provider.generate_json("sys", "user")


@pytest.mark.asyncio
async def test_sin_api_key_lanza_runtime_error():
    provider = GeminiProvider()
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            await provider.generate_json("sys", "user")


def test_safe_json_loads_extrae_json_embebido():
    provider = GeminiProvider()
    raw = 'texto previo {"a": 1} texto posterior'
    assert provider._safe_json_loads(raw) == {"a": 1}


def test_safe_json_loads_parsea_json_plano():
    provider = GeminiProvider()
    assert provider._safe_json_loads('{"a": 1}') == {"a": 1}
