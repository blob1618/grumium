"""Tests for sidebar configuration logic (non-UI parts)."""

from unittest.mock import patch


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
