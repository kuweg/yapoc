import base64
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

from . import BaseTool


class GenerateImageTool(BaseTool):
    name = "generate_image"
    description = (
        "Generate an image using OpenAI's gpt-image-1 model and save it under "
        "data/generated/. Returns JSON with the saved path and a UI-renderable "
        "URL (/api/files/image?path=...)."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "The image-generation prompt.",
            },
            "size": {
                "type": "string",
                "enum": ["1024x1024", "1536x1024", "1024x1536", "auto"],
                "default": "1024x1024",
                "description": "Output image dimensions.",
            },
            "quality": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "default": "medium",
                "description": "Image quality level.",
            },
        },
        "required": ["prompt"],
    }

    async def execute(self, **params: Any) -> str:
        try:
            api_key = settings.openai_api_key
            if not api_key:
                return "ERROR: OpenAI API key is not configured"

            prompt = params.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                return "ERROR: prompt must be a non-empty string"

            size = params.get("size", "1024x1024")
            quality = params.get("quality", "medium")
            valid_sizes = {"1024x1024", "1536x1024", "1024x1536", "auto"}
            valid_qualities = {"low", "medium", "high"}
            if size not in valid_sizes:
                return "ERROR: size must be one of 1024x1024, 1536x1024, 1024x1536, auto"
            if quality not in valid_qualities:
                return "ERROR: quality must be one of low, medium, high"

            slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")[:60] or "image"
            suffix = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
            relative_path = Path("data") / "generated" / f"{slug}_{suffix}.png"
            output_path = Path(settings.project_root) / relative_path
            output_path.parent.mkdir(parents=True, exist_ok=True)

            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.post(
                    "https://api.openai.com/v1/images/generations",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": "gpt-image-1",
                        "prompt": prompt,
                        "size": size,
                        "quality": quality,
                        "response_format": "b64_json",
                    },
                )

            if response.is_error:
                detail = response.text
                try:
                    payload = response.json()
                    error = payload.get("error", {})
                    if isinstance(error, dict):
                        detail = error.get("message") or detail
                except (ValueError, TypeError):
                    pass
                return f"ERROR: OpenAI image API error ({response.status_code}): {detail}"

            payload = response.json()
            image_b64 = payload["data"][0]["b64_json"]
            image_bytes = base64.b64decode(image_b64)
            output_path.write_bytes(image_bytes)

            path = relative_path.as_posix()
            return json.dumps(
                {
                    "type": "image_generated",
                    "path": path,
                    "url": f"/api/files/image?path={path}",
                    "media_type": "image/png",
                    "size_bytes": len(image_bytes),
                }
            )
        except Exception as exc:
            return f"ERROR: {exc}"
