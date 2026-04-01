#!/usr/bin/env python3
"""
Image Create Tool Module

Generate images using OpenAI-compatible providers (OpenAI, OpenRouter, custom endpoints).
Supports any provider that implements the OpenAI images/generation API format.

Available tools:
- image_create: Generate images from text prompts with optional upscaling

Features:
- Multi-provider support (OpenAI, OpenRouter, custom endpoints)
- Configurable aspect ratios (square, landscape, portrait)
- Quality control (standard, hd)
- Optional local upscaling via Pillow
- Automatic API key resolution per provider
- Graceful fallback if upscaling fails

Usage:
    from tools.image_tool import image_create_tool, check_image_create_requirements

    result = image_create_tool(prompt="A beautiful sunset over mountains")
"""

import io
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_PROVIDER = "openai"
DEFAULT_MODEL_MAP = {
    "openai": "dall-e-3",
    "openrouter": "openai/dall-e-3",
    "custom": "dall-e-3",
}
BASE_URL_MAP = {
    "openai": None,
    "openrouter": "https://openrouter.ai/api/v1",
    "custom": None,
}
API_KEY_ENV_MAP = {
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "custom": "IMAGE_GEN_API_KEY",
}

ASPECT_RATIO_TO_SIZE = {
    "square": "1024x1024",
    "landscape": "1792x1024",
    "portrait": "1024x1792",
}
VALID_ASPECT_RATIOS = list(ASPECT_RATIO_TO_SIZE.keys())
VALID_QUALITIES = ("standard", "hd")


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------
def _load_image_gen_config() -> dict:
    """Load image generation configuration from ~/.hermes/config.yaml."""
    try:
        from hermes_cli.config import load_config
        return load_config().get("image_gen", {})
    except (ImportError, Exception) as e:
        logger.debug("Failed to load image_gen config: %s", e)
        return {}


# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------
def _resolve_provider(config: dict) -> dict:
    """Resolve provider settings into (provider, api_key, base_url, model).

    Args:
        config: The image_gen config dict.

    Returns:
        dict with keys: provider, api_key, base_url, model
    """
    provider = (config.get("provider") or DEFAULT_PROVIDER).lower().strip()
    if provider not in API_KEY_ENV_MAP:
        provider = DEFAULT_PROVIDER

    env_var = API_KEY_ENV_MAP[provider]
    api_key = os.getenv(env_var, "")

    # Base URL: config override > env var > provider default
    base_url = config.get("base_url") or ""
    if not base_url and provider == "custom":
        base_url = os.getenv("IMAGE_GEN_BASE_URL", "")
    if not base_url:
        base_url = BASE_URL_MAP.get(provider)

    # Model: config override > provider default
    model = config.get("model") or ""
    if not model:
        model = DEFAULT_MODEL_MAP.get(provider, "dall-e-3")

    return {
        "provider": provider,
        "api_key": api_key,
        "base_url": base_url or None,
        "model": model,
    }


# ---------------------------------------------------------------------------
# Image generation
# ---------------------------------------------------------------------------
def _generate_image(
    prompt: str,
    model: str,
    api_key: str,
    base_url: Optional[str],
    size: str,
    quality: str,
) -> str:
    """Generate an image via the OpenAI images/generation API.

    Args:
        prompt: Text description of the desired image.
        model: Model slug (e.g. "dall-e-3").
        api_key: API key for the provider.
        base_url: Optional base URL for custom endpoints.
        size: Image size string (e.g. "1024x1024").
        quality: "standard" or "hd".

    Returns:
        URL of the generated image.

    Raises:
        ImportError: If the openai package is not installed.
        Exception: On API errors.
    """
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.images.generate(
        model=model,
        prompt=prompt,
        size=size,
        quality=quality,
        n=1,
    )
    url = response.data[0].url
    if not url:
        raise ValueError("API returned image without a URL")
    return url


# ---------------------------------------------------------------------------
# Upscaling
# ---------------------------------------------------------------------------
def _upscale_image(
    image_url: str,
    max_width: int,
    max_height: int,
    output_dir: Path,
) -> Optional[str]:
    """Download image, upscale with Pillow LANCZOS, save locally.

    Args:
        image_url: Remote URL of the image.
        max_width: Maximum target width.
        max_height: Maximum target height.
        output_dir: Directory to save the upscaled image.

    Returns:
        Local file path string on success, None if upscaling is not needed or fails.
    """
    try:
        import requests
        from PIL import Image
    except ImportError:
        logger.debug("Pillow or requests not installed, skipping upscale")
        return None

    try:
        resp = requests.get(image_url, timeout=30)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content))

        scale = min(max_width / img.width, max_height / img.height)
        if scale <= 1.0:
            return None  # Already at or above target

        new_size = (int(img.width * scale), int(img.height * scale))
        img = img.resize(new_size, Image.Resampling.LANCZOS)

        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"image_{int(time.time())}.png"
        filepath = output_dir / filename
        img.save(filepath, format="PNG")
        return str(filepath)
    except Exception as e:
        logger.warning("Upscaling failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Main tool function
# ---------------------------------------------------------------------------
def image_create_tool(
    prompt: str,
    aspect_ratio: str = "square",
    size: Optional[str] = None,
    quality: str = "standard",
) -> str:
    """Generate an image from a text prompt using an OpenAI-compatible provider.

    Args:
        prompt: Text description of the desired image.
        aspect_ratio: "landscape", "square", or "portrait" (default: "square").
        size: Override model size (e.g. "1024x1024"). If None, derived from aspect_ratio.
        quality: "standard" or "hd" (default: "standard").

    Returns:
        JSON string with success/error result.
    """
    try:
        if not prompt or not isinstance(prompt, str) or not prompt.strip():
            return json.dumps({"error": "prompt is required and must be a non-empty string"}, ensure_ascii=False)

        aspect_ratio = (aspect_ratio or "square").lower().strip()
        if aspect_ratio not in VALID_ASPECT_RATIOS:
            logger.warning("Invalid aspect_ratio '%s', defaulting to 'square'", aspect_ratio)
            aspect_ratio = "square"

        quality = (quality or "standard").lower().strip()
        if quality not in VALID_QUALITIES:
            logger.warning("Invalid quality '%s', defaulting to 'standard'", quality)
            quality = "standard"

        image_size = size if size else ASPECT_RATIO_TO_SIZE[aspect_ratio]

        config = _load_image_gen_config()
        provider_info = _resolve_provider(config)

        if not provider_info["api_key"]:
            env_var = API_KEY_ENV_MAP.get(provider_info["provider"], "API_KEY")
            return json.dumps(
                {"error": f"API key not set. Set the {env_var} environment variable."},
                ensure_ascii=False,
            )

        logger.info(
            "Generating image with %s (%s): %s",
            provider_info["provider"],
            provider_info["model"],
            prompt[:80],
        )

        image_url = _generate_image(
            prompt=prompt.strip(),
            model=provider_info["model"],
            api_key=provider_info["api_key"],
            base_url=provider_info["base_url"],
            size=image_size,
            quality=quality,
        )

        # Attempt upscaling
        upscaled_path = None
        upscale_config = config.get("upscale", {})
        if upscale_config.get("enabled", True):
            max_width = upscale_config.get("max_width", 2048)
            max_height = upscale_config.get("max_height", 2048)
            output_dir = get_hermes_home() / "images"
            upscaled_path = _upscale_image(image_url, max_width, max_height, output_dir)

        result_url = upscaled_path if upscaled_path else image_url

        result = {
            "success": True,
            "image": result_url,
            "provider": provider_info["provider"],
            "model": provider_info["model"],
        }
        if upscaled_path:
            result["upscaled"] = True

        return json.dumps(result, ensure_ascii=False)

    except ImportError as e:
        logger.error("Missing dependency: %s", e)
        return json.dumps({"error": f"Missing dependency: {e}"}, ensure_ascii=False)
    except Exception as e:
        logger.error("Error generating image: %s", e, exc_info=True)
        return json.dumps({"error": f"Error generating image: {e}"}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Requirements check
# ---------------------------------------------------------------------------
def check_image_create_requirements() -> bool:
    """Check if requirements for image_create are met.

    Returns True if any provider's API key is set AND
    the openai package is importable.
    """
    try:
        import openai  # noqa: F401 — SDK presence check
    except ImportError:
        return False

    # Check if any of the supported API keys are set (consistent with hermes setup)
    return bool(
        os.getenv("OPENAI_API_KEY")
        or os.getenv("OPENROUTER_API_KEY")
        or os.getenv("IMAGE_GEN_API_KEY")
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
from tools.registry import registry

IMAGE_CREATE_SCHEMA = {
    "name": "image_create",
    "description": "Generate images from text prompts using OpenAI-compatible providers (OpenAI DALL-E 3, OpenRouter, or custom endpoints). Returns a URL to the generated image. Display it using markdown: ![description](URL)",
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Detailed text description of the image to generate. Be specific and descriptive.",
            },
            "aspect_ratio": {
                "type": "string",
                "enum": ["landscape", "square", "portrait"],
                "description": "Aspect ratio of the generated image. 'landscape' is wide (1792x1024), 'portrait' is tall (1024x1792), 'square' is 1:1 (1024x1024).",
                "default": "square",
            },
            "size": {
                "type": "string",
                "description": "Override the image size (e.g. '1024x1024', '1792x1024', '1024x1792'). If not provided, size is derived from aspect_ratio.",
            },
            "quality": {
                "type": "string",
                "enum": ["standard", "hd"],
                "description": "Image quality. 'standard' is faster, 'hd' is higher detail.",
                "default": "standard",
            },
        },
        "required": ["prompt"],
    },
}


def _handle_image_create(args, **kw):
    prompt = args.get("prompt", "")
    if not prompt:
        return json.dumps({"error": "prompt is required for image generation"})
    return image_create_tool(
        prompt=prompt,
        aspect_ratio=args.get("aspect_ratio", "square"),
        size=args.get("size"),
        quality=args.get("quality", "standard"),
    )


registry.register(
    name="image_create",
    toolset="image_create",
    schema=IMAGE_CREATE_SCHEMA,
    handler=_handle_image_create,
    check_fn=check_image_create_requirements,
    requires_env=["OPENAI_API_KEY", "OPENROUTER_API_KEY", "IMAGE_GEN_API_KEY"],
    is_async=False,
    emoji="🖼️",
)
