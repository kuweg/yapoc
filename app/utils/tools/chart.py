import copy
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from app.config import settings

from . import BaseTool


# Curated colourblind-safe palette (Tableau 10). Applied as the default series
# colour list so every chart is legible for common colour-vision deficiencies,
# while still letting callers override with their own explicit `color` list.
COLORBLIND_PALETTE = [
    "#4E79A7",  # blue
    "#F28E2B",  # orange
    "#E15759",  # red
    "#76B7B2",  # teal
    "#59A14F",  # green
    "#EDC948",  # yellow
    "#B07AA1",  # purple
    "#FF9DA7",  # pink
    "#9C755F",  # brown
    "#BAB0AC",  # gray
]


def _normalize_option(option: Any) -> dict[str, Any] | str:
    """Validate and normalize an ECharts option without mutating the caller."""
    if not isinstance(option, dict):
        return "ERROR: option must be an object"

    series = option.get("series")
    if series is None or not (
        isinstance(series, list) and len(series) > 0 or isinstance(series, dict)
    ):
        return "ERROR: option must contain a non-empty 'series' array"

    normalized = copy.deepcopy(option)
    if isinstance(normalized.get("series"), dict):
        normalized["series"] = [normalized["series"]]
    if not isinstance(normalized["series"], list) or not normalized["series"]:
        return "ERROR: option must contain a non-empty 'series' array"

    normalized["animation"] = False
    # ECharts needs axes inferred explicitly for simple cartesian bar/line
    # series when no axis configuration was supplied by the caller.
    cartesian_types = {"bar", "line", "scatter", "effectScatter"}
    if any(isinstance(item, dict) and item.get("type") in cartesian_types for item in normalized["series"]):
        normalized.setdefault("xAxis", {"type": "category"})
        normalized.setdefault("yAxis", {"type": "value"})
    if "color" not in normalized:
        normalized["color"] = copy.deepcopy(COLORBLIND_PALETTE)
    return normalized


class RenderChartTool(BaseTool):
    name = "render_chart"
    description = (
        "Render an interactive ECharts chart in the chat. Pass a valid ECharts "
        "option object (series, xAxis, yAxis, title, tooltip, legend, etc.). "
        "Returns the normalized option JSON for the frontend to render."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "option": {
                "type": "object",
                "description": (
                    "ECharts option object (see https://echarts.apache.org/en/option.html). "
                    "Must contain at least a `series` array."
                ),
            },
        },
        "required": ["option"],
    }

    async def execute(self, **params: Any) -> str:
        try:
            normalized = _normalize_option(params.get("option"))
            if isinstance(normalized, str):
                return normalized
            return json.dumps(normalized, ensure_ascii=False)
        except Exception as exc:
            return f"ERROR: {exc}"


class RenderChartImageTool(BaseTool):
    name = "render_chart_image"
    description = (
        "Render an ECharts chart option into a PNG image file saved under data/generated/. "
        "Returns JSON with the saved path (pass this path to send_telegram_media to send "
        "the image to Telegram). Pass a valid ECharts option object."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "option": {
                "type": "object",
                "description": "ECharts option object with a series array",
            },
            "width": {"type": "integer", "default": 800},
            "height": {"type": "integer", "default": 500},
            "title": {"type": "string", "description": "Optional filename slug"},
        },
        "required": ["option"],
    }

    async def execute(self, **params: Any) -> str:
        browser = None
        playwright = None
        try:
            normalized = _normalize_option(params.get("option"))
            if isinstance(normalized, str):
                return normalized

            width = params.get("width", 800)
            height = params.get("height", 500)
            if not isinstance(width, int) or isinstance(width, bool) or width <= 0:
                return "ERROR: width must be a positive integer"
            if not isinstance(height, int) or isinstance(height, bool) or height <= 0:
                return "ERROR: height must be a positive integer"

            title = params.get("title", "chart")
            if title is not None and not isinstance(title, str):
                return "ERROR: title must be a string"
            slug = re.sub(r"[^a-z0-9]+", "-", (title or "chart").lower()).strip("-")[:60] or "chart"
            suffix = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
            relative_path = Path("data") / "generated" / f"{slug}_{suffix}.png"
            output_path = Path(settings.project_root) / relative_path
            output_path.parent.mkdir(parents=True, exist_ok=True)

            echarts_path = (
                Path(settings.project_root)
                / "app"
                / "frontend"
                / "node_modules"
                / "echarts"
                / "dist"
                / "echarts.min.js"
            )
            if not echarts_path.is_file():
                return f"ERROR: local ECharts bundle is unavailable: {echarts_path}"
            echarts_source = echarts_path.read_text(encoding="utf-8")
            option_json = json.dumps(normalized, ensure_ascii=False).replace("</", "<\\/")
            html = f"""<!doctype html>
<html><head><meta charset=\"utf-8\"><style>
html, body, #chart {{ margin: 0; width: {width}px; height: {height}px; overflow: hidden; }}
</style></head><body><div id=\"chart\"></div><script>{echarts_source}</script><script>
try {{
  const chart = echarts.init(document.getElementById('chart'), null, {{ renderer: 'canvas', width: {width}, height: {height} }});
  chart.setOption({option_json});
  window.__chartReady = true;
}} catch (error) {{
  window.__chartError = String(error && error.stack || error);
}}
</script></body></html>"""

            try:
                from playwright.async_api import async_playwright
            except ImportError:
                return "ERROR: Playwright is unavailable; install the playwright package and Chromium browser"

            playwright = await async_playwright().start()
            try:
                browser = await playwright.chromium.launch(headless=True)
            except Exception as exc:
                return f"ERROR: Playwright Chromium is unavailable: {exc}"
            page = await browser.new_page(viewport={"width": width, "height": height})
            await page.set_content(html, wait_until="load")
            await page.wait_for_function(
                "window.__chartReady === true || window.__chartError",
                timeout=10_000,
            )
            chart_error = await page.evaluate("window.__chartError || null")
            if chart_error:
                return f"ERROR: ECharts render failed: {chart_error}"
            await page.locator("#chart").screenshot(path=str(output_path))

            image_bytes = output_path.read_bytes()
            if not image_bytes.startswith(b"\x89PNG"):
                return "ERROR: chart renderer did not produce a valid PNG"
            path = relative_path.as_posix()
            return json.dumps(
                {
                    "type": "chart_image",
                    "path": path,
                    "url": f"/api/files/image?path={path}",
                    "media_type": "image/png",
                    "size_bytes": len(image_bytes),
                }
            )
        except Exception as exc:
            return f"ERROR: {exc}"
        finally:
            if browser is not None:
                await browser.close()
            if playwright is not None:
                await playwright.stop()
