import json
from pathlib import Path

import pytest

pytest.importorskip("playwright.async_api")

from app.config import settings
from app.utils.tools.chart import RenderChartImageTool


@pytest.mark.asyncio
async def test_render_chart_image_creates_png():
    result = await RenderChartImageTool().execute(
        option={"series": [{"type": "bar", "data": [1, 2, 3]}]},
        width=400,
        height=300,
    )
    if result.startswith("ERROR: Playwright Chromium is unavailable"):
        pytest.skip(result)

    payload = json.loads(result)
    assert payload["type"] == "chart_image"
    assert payload["path"]

    output_path = Path(settings.project_root) / payload["path"]
    try:
        image_bytes = output_path.read_bytes()
        assert image_bytes
        assert image_bytes.startswith(b"\x89PNG")
    finally:
        output_path.unlink(missing_ok=True)
