"""Tests for chat state management and export logic."""

import json


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
            {"role": "user", "content": 'Gasté $5.000 en "super"', "debug": {}},
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
