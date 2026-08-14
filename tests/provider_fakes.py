"""Fakes compartidos para tests de proveedores LLM (sin red real)."""

import httpx


class FakeResponse:
    def __init__(self, status_code, text="", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self.url = httpx.URL("https://provider.example/v1/models/x:generateContent")

    def raise_for_status(self):
        if 400 <= self.status_code < 600:
            request = httpx.Request("POST", str(self.url))
            raise httpx.HTTPStatusError("error", request=request, response=self)

    def json(self):
        if self.status_code == 200 and self.text:
            return {
                "candidates": [{"content": {"parts": [{"text": self.text}]}}],
                "choices": [{"message": {"content": self.text}}],
            }
        return {"error": {"code": self.status_code, "message": "boom"}}


class FakeAsyncClient:
    """Cliente httpx simulado: consume una lista de respuestas en orden."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requested_urls = []
        self.requested_bodies = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        self.requested_urls.append(str(url))
        self.requested_bodies.append(kwargs.get("json"))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response
