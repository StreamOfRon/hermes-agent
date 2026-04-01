"""Tests for the image_create tool module."""

import io
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MOCK_IMAGE_URL = "https://example.com/generated-image.png"


def _make_mock_image_response(url=MOCK_IMAGE_URL):
    """Create a mock OpenAI image generation response."""
    mock_data = MagicMock()
    mock_data.url = url
    mock_response = MagicMock()
    mock_response.data = [mock_data]
    return mock_response


def _make_pil_image(width=1024, height=1024):
    """Create a minimal PIL Image for testing."""
    from PIL import Image
    return Image.new("RGB", (width, height), color="red")


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

class TestLoadImageGenConfig:
    def test_returns_image_gen_section(self):
        from tools.image_tool import _load_image_gen_config
        with patch("hermes_cli.config.load_config") as mock_load:
            mock_load.return_value = {
                "image_gen": {"provider": "openrouter", "model": "test-model"},
                "other_key": "value",
            }
            result = _load_image_gen_config()
            assert result == {"provider": "openrouter", "model": "test-model"}

    def test_returns_empty_dict_on_import_error(self):
        from tools.image_tool import _load_image_gen_config
        with patch("hermes_cli.config.load_config", side_effect=ImportError):
            result = _load_image_gen_config()
            assert result == {}

    def test_returns_empty_dict_on_exception(self):
        from tools.image_tool import _load_image_gen_config
        with patch("hermes_cli.config.load_config", side_effect=Exception("boom")):
            result = _load_image_gen_config()
            assert result == {}

    def test_returns_empty_dict_if_key_missing(self):
        from tools.image_tool import _load_image_gen_config
        with patch("hermes_cli.config.load_config") as mock_load:
            mock_load.return_value = {"other_key": "value"}
            result = _load_image_gen_config()
            assert result == {}


# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------

class TestResolveProvider:
    def test_openai_defaults(self, monkeypatch):
        from tools.image_tool import _resolve_provider
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        result = _resolve_provider({"provider": "openai"})
        assert result["provider"] == "openai"
        assert result["api_key"] == "sk-test"
        assert result["base_url"] is None
        assert result["model"] == "dall-e-3"

    def test_openrouter_defaults(self, monkeypatch):
        from tools.image_tool import _resolve_provider
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        result = _resolve_provider({"provider": "openrouter"})
        assert result["provider"] == "openrouter"
        assert result["api_key"] == "sk-or-test"
        assert result["base_url"] == "https://openrouter.ai/api/v1"
        assert result["model"] == "openai/dall-e-3"

    def test_custom_defaults(self, monkeypatch):
        from tools.image_tool import _resolve_provider
        monkeypatch.setenv("IMAGE_GEN_API_KEY", "custom-key")
        monkeypatch.setenv("IMAGE_GEN_BASE_URL", "http://localhost:8080/v1")
        result = _resolve_provider({"provider": "custom"})
        assert result["provider"] == "custom"
        assert result["api_key"] == "custom-key"
        assert result["base_url"] == "http://localhost:8080/v1"
        assert result["model"] == "dall-e-3"

    def test_custom_with_config_overrides(self, monkeypatch):
        from tools.image_tool import _resolve_provider
        monkeypatch.setenv("IMAGE_GEN_API_KEY", "custom-key")
        config = {
            "provider": "custom",
            "model": "my-custom-model",
            "base_url": "http://my-server/v1",
        }
        result = _resolve_provider(config)
        assert result["model"] == "my-custom-model"
        assert result["base_url"] == "http://my-server/v1"

    def test_invalid_provider_falls_back_to_openai(self, monkeypatch):
        from tools.image_tool import _resolve_provider
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        result = _resolve_provider({"provider": "invalid"})
        assert result["provider"] == "openai"

    def test_config_model_overrides_default(self, monkeypatch):
        from tools.image_tool import _resolve_provider
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        result = _resolve_provider({"provider": "openai", "model": "dall-e-2"})
        assert result["model"] == "dall-e-2"

    def test_empty_api_key(self):
        from tools.image_tool import _resolve_provider
        result = _resolve_provider({"provider": "openai"})
        assert result["api_key"] == ""

    def test_none_provider_falls_back(self, monkeypatch):
        from tools.image_tool import _resolve_provider
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        result = _resolve_provider({"provider": None})
        assert result["provider"] == "openai"

    def test_empty_config(self, monkeypatch):
        from tools.image_tool import _resolve_provider
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        result = _resolve_provider({})
        assert result["provider"] == "openai"
        assert result["api_key"] == "sk-test"


# ---------------------------------------------------------------------------
# Image generation
# ---------------------------------------------------------------------------

class TestGenerateImage:
    def test_calls_openai_with_correct_params(self, monkeypatch):
        from tools.image_tool import _generate_image
        mock_client = MagicMock()
        mock_client.images.generate.return_value = _make_mock_image_response()

        with patch("openai.OpenAI", return_value=mock_client) as mock_openai:
            url = _generate_image(
                prompt="a cat",
                model="dall-e-3",
                api_key="sk-test",
                base_url=None,
                size="1024x1024",
                quality="standard",
            )

        mock_openai.assert_called_once_with(api_key="sk-test", base_url=None)
        mock_client.images.generate.assert_called_once_with(
            model="dall-e-3",
            prompt="a cat",
            size="1024x1024",
            quality="standard",
            n=1,
        )
        assert url == MOCK_IMAGE_URL

    def test_passes_base_url(self, monkeypatch):
        from tools.image_tool import _generate_image
        mock_client = MagicMock()
        mock_client.images.generate.return_value = _make_mock_image_response()

        with patch("openai.OpenAI", return_value=mock_client) as mock_openai:
            _generate_image(
                prompt="test",
                model="test-model",
                api_key="key",
                base_url="http://localhost:8080/v1",
                size="1024x1024",
                quality="hd",
            )

        mock_openai.assert_called_once_with(
            api_key="key",
            base_url="http://localhost:8080/v1",
        )

    def test_raises_on_missing_url(self, monkeypatch):
        from tools.image_tool import _generate_image
        mock_data = MagicMock()
        mock_data.url = None
        mock_response = MagicMock()
        mock_response.data = [mock_data]
        mock_client = MagicMock()
        mock_client.images.generate.return_value = mock_response

        with patch("openai.OpenAI", return_value=mock_client):
            with pytest.raises(ValueError, match="without a URL"):
                _generate_image(
                    prompt="test", model="m", api_key="k",
                    base_url=None, size="1024x1024", quality="standard",
                )


# ---------------------------------------------------------------------------
# Upscaling
# ---------------------------------------------------------------------------

class TestUpscaleImage:
    def test_returns_none_when_already_at_target(self, tmp_path, monkeypatch):
        from tools.image_tool import _upscale_image
        img = _make_pil_image(width=2048, height=2048)
        buf = io.BytesIO()
        img.save(buf, format="PNG")

        mock_resp = MagicMock()
        mock_resp.content = buf.getvalue()
        mock_resp.raise_for_status = MagicMock()

        with patch("requests.get", return_value=mock_resp):
            result = _upscale_image(
                "http://example.com/img.png",
                max_width=2048,
                max_height=2048,
                output_dir=tmp_path,
            )
        assert result is None

    def test_upscales_smaller_image(self, tmp_path, monkeypatch):
        from tools.image_tool import _upscale_image
        img = _make_pil_image(width=512, height=512)
        buf = io.BytesIO()
        img.save(buf, format="PNG")

        mock_resp = MagicMock()
        mock_resp.content = buf.getvalue()
        mock_resp.raise_for_status = MagicMock()

        with patch("requests.get", return_value=mock_resp):
            result = _upscale_image(
                "http://example.com/img.png",
                max_width=2048,
                max_height=2048,
                output_dir=tmp_path,
            )

        assert result is not None
        assert result.endswith(".png")
        assert Path(result).exists()

    def test_returns_none_on_download_failure(self, tmp_path):
        from tools.image_tool import _upscale_image
        with patch("requests.get", side_effect=Exception("download failed")):
            result = _upscale_image(
                "http://example.com/img.png",
                max_width=2048,
                max_height=2048,
                output_dir=tmp_path,
            )
        assert result is None

    def test_returns_none_when_pillow_missing(self, tmp_path):
        from tools.image_tool import _upscale_image
        with patch.dict("sys.modules", {"PIL": None, "PIL.Image": None}):
            result = _upscale_image(
                "http://example.com/img.png",
                max_width=2048,
                max_height=2048,
                output_dir=tmp_path,
            )
        assert result is None

    def test_creates_output_directory(self, tmp_path):
        from tools.image_tool import _upscale_image
        img = _make_pil_image(width=512, height=512)
        buf = io.BytesIO()
        img.save(buf, format="PNG")

        mock_resp = MagicMock()
        mock_resp.content = buf.getvalue()
        mock_resp.raise_for_status = MagicMock()

        output_dir = tmp_path / "nested" / "dir"
        with patch("requests.get", return_value=mock_resp):
            result = _upscale_image(
                "http://example.com/img.png",
                max_width=2048,
                max_height=2048,
                output_dir=output_dir,
            )

        assert result is not None
        assert output_dir.exists()


# ---------------------------------------------------------------------------
# Main tool function
# ---------------------------------------------------------------------------

class TestImageCreateTool:
    def test_empty_prompt_returns_error(self):
        from tools.image_tool import image_create_tool
        result = json.loads(image_create_tool(prompt=""))
        assert "error" in result

    def test_none_prompt_returns_error(self):
        from tools.image_tool import image_create_tool
        result = json.loads(image_create_tool(prompt=None))
        assert "error" in result

    def test_whitespace_only_prompt_returns_error(self):
        from tools.image_tool import image_create_tool
        result = json.loads(image_create_tool(prompt="   "))
        assert "error" in result

    def test_invalid_aspect_ratio_defaults_to_square(self, monkeypatch):
        from tools.image_tool import image_create_tool
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_response = _make_mock_image_response()
        mock_client = MagicMock()
        mock_client.images.generate.return_value = mock_response

        with patch("openai.OpenAI", return_value=mock_client):
            with patch("hermes_cli.config.load_config", return_value={"image_gen": {}}):
                result = json.loads(image_create_tool(
                    prompt="test", aspect_ratio="invalid"
                ))

        call_args = mock_client.images.generate.call_args
        assert call_args.kwargs["size"] == "1024x1024"
        assert result["success"] is True

    def test_landscape_aspect_ratio(self, monkeypatch):
        from tools.image_tool import image_create_tool
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_response = _make_mock_image_response()
        mock_client = MagicMock()
        mock_client.images.generate.return_value = mock_response

        with patch("openai.OpenAI", return_value=mock_client):
            with patch("hermes_cli.config.load_config", return_value={"image_gen": {}}):
                result = json.loads(image_create_tool(
                    prompt="test", aspect_ratio="landscape"
                ))

        call_args = mock_client.images.generate.call_args
        assert call_args.kwargs["size"] == "1792x1024"

    def test_portrait_aspect_ratio(self, monkeypatch):
        from tools.image_tool import image_create_tool
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_response = _make_mock_image_response()
        mock_client = MagicMock()
        mock_client.images.generate.return_value = mock_response

        with patch("openai.OpenAI", return_value=mock_client):
            with patch("hermes_cli.config.load_config", return_value={"image_gen": {}}):
                result = json.loads(image_create_tool(
                    prompt="test", aspect_ratio="portrait"
                ))

        call_args = mock_client.images.generate.call_args
        assert call_args.kwargs["size"] == "1024x1792"

    def test_custom_size_override(self, monkeypatch):
        from tools.image_tool import image_create_tool
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_response = _make_mock_image_response()
        mock_client = MagicMock()
        mock_client.images.generate.return_value = mock_response

        with patch("openai.OpenAI", return_value=mock_client):
            with patch("hermes_cli.config.load_config", return_value={"image_gen": {}}):
                result = json.loads(image_create_tool(
                    prompt="test", size="256x256"
                ))

        call_args = mock_client.images.generate.call_args
        assert call_args.kwargs["size"] == "256x256"

    def test_hd_quality(self, monkeypatch):
        from tools.image_tool import image_create_tool
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_response = _make_mock_image_response()
        mock_client = MagicMock()
        mock_client.images.generate.return_value = mock_response

        with patch("openai.OpenAI", return_value=mock_client):
            with patch("hermes_cli.config.load_config", return_value={"image_gen": {}}):
                result = json.loads(image_create_tool(
                    prompt="test", quality="hd"
                ))

        call_args = mock_client.images.generate.call_args
        assert call_args.kwargs["quality"] == "hd"

    def test_invalid_quality_defaults_to_standard(self, monkeypatch):
        from tools.image_tool import image_create_tool
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_response = _make_mock_image_response()
        mock_client = MagicMock()
        mock_client.images.generate.return_value = mock_response

        with patch("openai.OpenAI", return_value=mock_client):
            with patch("hermes_cli.config.load_config", return_value={"image_gen": {}}):
                result = json.loads(image_create_tool(
                    prompt="test", quality="ultra"
                ))

        call_args = mock_client.images.generate.call_args
        assert call_args.kwargs["quality"] == "standard"

    def test_missing_api_key_returns_error(self, monkeypatch):
        from tools.image_tool import image_create_tool
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("IMAGE_GEN_API_KEY", raising=False)

        result = json.loads(image_create_tool(prompt="test"))
        assert "error" in result
        assert "API key not set" in result["error"]

    def test_openai_provider_uses_correct_env(self, monkeypatch):
        from tools.image_tool import image_create_tool
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        mock_response = _make_mock_image_response()
        mock_client = MagicMock()
        mock_client.images.generate.return_value = mock_response

        with patch("openai.OpenAI", return_value=mock_client):
            with patch("hermes_cli.config.load_config", return_value={
                "provider": "openai"
            }):
                result = json.loads(image_create_tool(prompt="test"))

        assert result["success"] is True
        assert result["provider"] == "openai"

    def test_openrouter_provider_uses_correct_env(self, monkeypatch):
        from tools.image_tool import image_create_tool
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        mock_response = _make_mock_image_response()
        mock_client = MagicMock()
        mock_client.images.generate.return_value = mock_response

        with patch("openai.OpenAI", return_value=mock_client):
            with patch("hermes_cli.config.load_config", return_value={
                "image_gen": {"provider": "openrouter"}
            }):
                result = json.loads(image_create_tool(prompt="test"))

        assert result["success"] is True
        assert result["provider"] == "openrouter"

    def test_custom_provider_uses_correct_env(self, monkeypatch):
        from tools.image_tool import image_create_tool
        monkeypatch.setenv("IMAGE_GEN_API_KEY", "sk-custom")
        monkeypatch.setenv("IMAGE_GEN_BASE_URL", "http://localhost:8080/v1")
        mock_response = _make_mock_image_response()
        mock_client = MagicMock()
        mock_client.images.generate.return_value = mock_response

        with patch("openai.OpenAI", return_value=mock_client):
            with patch("hermes_cli.config.load_config", return_value={
                "image_gen": {"provider": "custom"}
            }):
                result = json.loads(image_create_tool(prompt="test"))

        assert result["success"] is True
        assert result["provider"] == "custom"

    def test_result_contains_model_and_provider(self, monkeypatch):
        from tools.image_tool import image_create_tool
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_response = _make_mock_image_response()
        mock_client = MagicMock()
        mock_client.images.generate.return_value = mock_response

        with patch("openai.OpenAI", return_value=mock_client):
            with patch("hermes_cli.config.load_config", return_value={"image_gen": {}}):
                result = json.loads(image_create_tool(prompt="test"))

        assert result["model"] == "dall-e-3"
        assert result["provider"] == "openai"

    def test_api_error_returns_json_error(self, monkeypatch):
        from tools.image_tool import image_create_tool
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_client = MagicMock()
        mock_client.images.generate.side_effect = Exception("API error")

        with patch("openai.OpenAI", return_value=mock_client):
            with patch("hermes_cli.config.load_config", return_value={"image_gen": {}}):
                result = json.loads(image_create_tool(prompt="test"))

        assert "error" in result
        assert "API error" in result["error"]

    def test_upscaled_flag_set_when_upscale_succeeds(self, monkeypatch, tmp_path):
        from tools.image_tool import image_create_tool
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_response = _make_mock_image_response()
        mock_client = MagicMock()
        mock_client.images.generate.return_value = mock_response

        with patch("openai.OpenAI", return_value=mock_client):
            with patch("hermes_cli.config.load_config", return_value={
                "image_gen": {"upscale": {"enabled": True, "max_width": 2048, "max_height": 2048}}
            }):
                with patch("tools.image_tool._upscale_image", return_value=str(tmp_path / "upscaled.png")):
                    with patch("tools.image_tool.get_hermes_home", return_value=tmp_path):
                        result = json.loads(image_create_tool(prompt="test"))

        assert result["success"] is True
        assert result.get("upscaled") is True

    def test_upscale_disabled_in_config(self, monkeypatch):
        from tools.image_tool import image_create_tool
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_response = _make_mock_image_response()
        mock_client = MagicMock()
        mock_client.images.generate.return_value = mock_response

        with patch("openai.OpenAI", return_value=mock_client):
            with patch("hermes_cli.config.load_config", return_value={
                "image_gen": {"upscale": {"enabled": False}}
            }):
                with patch("tools.image_tool._upscale_image") as mock_upscale:
                    result = json.loads(image_create_tool(prompt="test"))

        mock_upscale.assert_not_called()
        assert result["success"] is True
        assert "upscaled" not in result


# ---------------------------------------------------------------------------
# Requirements check
# ---------------------------------------------------------------------------

class TestCheckImageCreateRequirements:
    def test_returns_false_without_openai(self):
        from tools.image_tool import check_image_create_requirements
        with patch.dict("sys.modules", {"openai": None}):
            result = check_image_create_requirements()
        assert result is False

    def test_returns_false_without_api_key(self, monkeypatch):
        from tools.image_tool import check_image_create_requirements
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("IMAGE_GEN_API_KEY", raising=False)
        result = check_image_create_requirements()
        assert result is False

    def test_returns_true_with_openai_and_key(self, monkeypatch):
        from tools.image_tool import check_image_create_requirements
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        result = check_image_create_requirements()
        assert result is True

    def test_returns_true_with_openrouter_key(self, monkeypatch):
        from tools.image_tool import check_image_create_requirements
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        result = check_image_create_requirements()
        assert result is True

    def test_returns_true_with_custom_key(self, monkeypatch):
        from tools.image_tool import check_image_create_requirements
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.setenv("IMAGE_GEN_API_KEY", "sk-custom-test")
        result = check_image_create_requirements()
        assert result is True


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_tool_is_registered(self):
        from tools.registry import registry
        entry = registry._tools.get("image_create")
        assert entry is not None
        assert entry.toolset == "image_create"

    def test_tool_schema_has_required_fields(self):
        from tools.registry import registry
        entry = registry._tools.get("image_create")
        schema = entry.schema
        assert schema["name"] == "image_create"
        assert "prompt" in schema["parameters"]["required"]
        props = schema["parameters"]["properties"]
        assert "prompt" in props
        assert "aspect_ratio" in props
        assert "size" in props
        assert "quality" in props

    def test_handler_returns_json_error_on_empty_prompt(self):
        from tools.registry import registry
        entry = registry._tools.get("image_create")
        result = json.loads(entry.handler({"prompt": ""}))
        assert "error" in result

    def test_check_fn_registered(self):
        from tools.registry import registry
        entry = registry._tools.get("image_create")
        assert entry.check_fn is not None
        assert callable(entry.check_fn)
