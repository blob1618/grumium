"""El cliente Redis de ConversationService se vincula al event loop activo.

Cada rerun del entorno de testing ejecuta asyncio.run() con un loop nuevo;
reutilizar el cliente del loop anterior puede colgar las operaciones en
select(). Por eso el cliente se recrea cuando cambia el loop.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.services.conversation import ConversationService


class FakeLoop:
    """Objeto opaco que hace las veces de event loop (solo importa su id)."""


@pytest.fixture(autouse=True)
def _clean_client():
    ConversationService._client = None
    ConversationService._loop_id = None
    yield
    ConversationService._client = None
    ConversationService._loop_id = None


def _patch_loop(monkeypatch, loop):
    monkeypatch.setattr(
        "app.services.conversation.asyncio.get_running_loop",
        lambda: loop,
    )


def test_cambia_de_loop_recrea_el_cliente(monkeypatch):
    created = []

    def fake_from_url(url, **kwargs):
        client = AsyncMock()
        client.ping = AsyncMock()
        created.append(url)
        return client

    monkeypatch.setattr("app.services.conversation.redis.from_url", fake_from_url)

    _patch_loop(monkeypatch, FakeLoop())
    asyncio.run(ConversationService._get_client())

    _patch_loop(monkeypatch, FakeLoop())
    asyncio.run(ConversationService._get_client())

    assert len(created) == 2


def test_mismo_loop_reutiliza_el_cliente(monkeypatch):
    created = []

    def fake_from_url(url, **kwargs):
        client = AsyncMock()
        client.ping = AsyncMock()
        created.append(url)
        return client

    monkeypatch.setattr("app.services.conversation.redis.from_url", fake_from_url)

    loop = FakeLoop()
    _patch_loop(monkeypatch, loop)
    asyncio.run(ConversationService._get_client())
    asyncio.run(ConversationService._get_client())

    assert len(created) == 1


def test_ping_fallido_degrada_sin_romper(monkeypatch):
    def fake_from_url(url, **kwargs):
        client = AsyncMock()
        client.ping = AsyncMock(side_effect=ConnectionError("redis down"))
        return client

    monkeypatch.setattr("app.services.conversation.redis.from_url", fake_from_url)
    _patch_loop(monkeypatch, FakeLoop())

    client = asyncio.run(ConversationService._get_client())

    assert client is not None
