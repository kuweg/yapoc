"""render_chart_image writes a real PNG — and only inside a temp tree.

This test used to run against the live ``settings.project_root``: it wrote a
chart into the repository's own ``data/generated/`` on every run and deleted
the file afterwards. That was already untidy; once the tool started registering
its output, it also left a permanent artifact row pointing at a file the test
had just removed. Same shape as the 48 leaked ``tmp*`` memory directories the
harness roadmap's Phase 5 cleaned up — a test writing into the real project.
"""

import json
from pathlib import Path

import pytest

pytest.importorskip("playwright.async_api")

from app.config import settings
from app.utils.tools.chart import RenderChartImageTool


def _isolated_root(tmp_path, monkeypatch):
    """Point the tool at a temp project root, keeping the ECharts bundle reachable.

    The renderer inlines ``app/frontend/node_modules/echarts/dist/echarts.min.js``
    from the project root, so a bare temp root makes it fail with "local ECharts
    bundle is unavailable" rather than exercising anything. Symlinking the real
    bundle keeps the tool's contract intact while output and the artifact index
    stay inside tmp_path.
    """
    real_bundle = (
        Path(__file__).resolve().parents[3]
        / "app" / "frontend" / "node_modules" / "echarts" / "dist" / "echarts.min.js"
    )
    if not real_bundle.is_file():
        pytest.skip(f"ECharts bundle not installed at {real_bundle}")
    staged = tmp_path / "app" / "frontend" / "node_modules" / "echarts" / "dist"
    staged.mkdir(parents=True)
    (staged / "echarts.min.js").symlink_to(real_bundle)

    monkeypatch.setattr(type(settings), "project_root", property(lambda self: tmp_path))
    from app.backend.services import artifacts
    monkeypatch.setattr(artifacts, "_project_root", lambda: tmp_path)
    return artifacts



@pytest.mark.asyncio
async def test_render_chart_image_creates_png(tmp_path, monkeypatch):
    _isolated_root(tmp_path, monkeypatch)

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

    image_bytes = (Path(tmp_path) / payload["path"]).read_bytes()
    assert image_bytes.startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_render_chart_image_registers_its_output(tmp_path, monkeypatch):
    """The returned artifact_id must resolve to a real record."""
    artifacts = _isolated_root(tmp_path, monkeypatch)

    agent_dir = tmp_path / "app" / "agents" / "builder"
    agent_dir.mkdir(parents=True)
    (agent_dir / "TASK.MD").write_text("---\ntask_id: task-chart\n---\n")

    result = await RenderChartImageTool(agent_dir=agent_dir, session_id="sess-chart").execute(
        option={"series": [{"type": "bar", "data": [1, 2, 3]}]}, width=300, height=200,
    )
    if result.startswith("ERROR: Playwright Chromium is unavailable"):
        pytest.skip(result)

    payload = json.loads(result)
    record = artifacts.get_artifact(payload["artifact_id"])
    assert record is not None
    assert record["source_agent"] == "builder"
    assert record["source_task"] == "task-chart"
    assert record["source_session"] == "sess-chart"
