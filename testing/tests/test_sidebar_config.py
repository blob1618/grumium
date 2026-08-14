"""Tests for sidebar configuration logic (non-UI parts)."""

import os
from unittest.mock import patch


from testing.components.sidebar import get_available_models, get_available_prompts, get_available_providers
from testing.config.settings import set_model_env


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


class TestGetAvailableModels:
    def test_gemini_flash_primero(self):
        models = get_available_models("gemini")
        assert models[0] == "gemini-3.6-flash"
        assert "gemini-3.7-flash" in models
        assert "gemini-3.1-flash-lite" in models
        assert "gemini-3.1-pro-preview" in models

    def test_mistral_small_primero(self):
        models = get_available_models("mistral")
        assert models[0] == "mistral-small-latest"
        assert "ministral-3b-latest" in models

    def test_provider_desconocido_devuelve_lista_gemini(self):
        assert get_available_models("desconocido") == get_available_models("gemini")


class TestSetModelEnv:
    def test_setea_gemini_model(self, monkeypatch):
        monkeypatch.delenv("GEMINI_MODEL", raising=False)
        set_model_env("gemini", "gemini-3.5-flash")
        assert os.environ["GEMINI_MODEL"] == "gemini-3.5-flash"

    def test_setea_mistral_model(self, monkeypatch):
        monkeypatch.delenv("MISTRAL_MODEL", raising=False)
        set_model_env("mistral", "mistral-small-latest")
        assert os.environ["MISTRAL_MODEL"] == "mistral-small-latest"

    def test_modelo_vacio_no_toca_env(self, monkeypatch):
        monkeypatch.setenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
        set_model_env("gemini", "")
        assert os.environ["GEMINI_MODEL"] == "gemini-3.1-flash-lite"
