"""Skills router — manage skill definitions in app/skills/*.yaml.

GET /skills                          → list all skills (SkillOut array)
POST /skills                         → create a new skill
PUT /skills/{name}                   → update an existing skill
DELETE /skills/{name}                 → delete a skill
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings

router = APIRouter(prefix="/skills")

_SKILLS_ROOT: Path = settings.project_root / "app" / "skills"
_SKILL_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class SkillOut(BaseModel):
    name: str
    summary: Optional[str] = None
    description: Optional[str] = None
    levels: list[str] = []


class SkillWrite(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    summary: Optional[str] = None
    description: Optional[str] = None
    level_1: Optional[str] = None
    level_2: Optional[str] = None
    level_3: Optional[str] = None


def _parse_skill(path: Path) -> Optional[SkillOut]:
    """Parse a single skill YAML file, returning None on failure."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, OSError):
        return None

    if not isinstance(data, dict):
        return None

    name = str(data.get("name") or path.stem)
    summary = data.get("summary")
    if summary is not None:
        summary = str(summary)
    description = data.get("description")
    if description is not None:
        description = str(description)

    levels = [k for k in ("level_1", "level_2", "level_3") if data.get(k) is not None]

    return SkillOut(name=name, summary=summary, description=description, levels=levels)


def _read_skill_dict(name: str) -> dict:
    """Read a skill YAML file as a dict, raising HTTPException(404) if missing."""
    path = _SKILLS_ROOT / f"{name}.yaml"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Skill not found")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, OSError):
        raise HTTPException(status_code=422, detail="Skill file is corrupt")
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="Skill file is corrupt")
    return data


def _build_yaml(name: str, fields: dict) -> str:
    """Build a skill YAML document using the same manual line-format as the
    skills.py create_skill tool."""
    lines = [f"name: {name}"]
    summary = (fields.get("summary") or "").strip()
    description = (fields.get("description") or "").strip()
    level_1 = (fields.get("level_1") or "").strip()
    level_2 = (fields.get("level_2") or "").strip()
    level_3 = (fields.get("level_3") or "").strip()

    lines.append(f"summary: {summary}")
    if description:
        lines.append("description: |")
        for desc_line in description.split("\n"):
            lines.append(f"  {desc_line}")
    if level_1:
        lines.append(f"level_1: \"{level_1}\"")
    if level_2:
        lines.append("level_2: |")
        for l2_line in level_2.split("\n"):
            lines.append(f"  {l2_line}")
    if level_3:
        lines.append("level_3: |")
        for l3_line in level_3.split("\n"):
            lines.append(f"  {l3_line}")

    return "\n".join(lines)


@router.get("", response_model=list[SkillOut])
async def list_skills() -> list[SkillOut]:
    root = _SKILLS_ROOT.resolve()
    skills: list[SkillOut] = []
    if not root.is_dir():
        return skills

    for entry in sorted(root.iterdir(), key=lambda e: e.name.lower()):
        if not entry.is_file() or entry.suffix.lower() != ".yaml":
            continue
        skill = _parse_skill(entry)
        if skill is not None:
            skills.append(skill)

    skills.sort(key=lambda s: s.name.lower())
    return skills


@router.post("", response_model=SkillOut, status_code=201)
async def create_skill(payload: SkillWrite) -> SkillOut:
    if not _SKILL_NAME_RE.match(payload.name):
        raise HTTPException(
            status_code=422,
            detail="Invalid skill name. Must start with a letter or underscore and contain only alphanumeric characters and underscores.",
        )

    if not payload.level_1:
        raise HTTPException(
            status_code=400,
            detail="At minimum a name and level_1 are required.",
        )

    path = _SKILLS_ROOT / f"{payload.name}.yaml"
    if path.exists():
        raise HTTPException(status_code=409, detail="Skill already exists")

    write = SkillWrite(
        name=payload.name,
        summary=payload.summary,
        description=payload.description,
        level_1=payload.level_1,
        level_2=payload.level_2,
        level_3=payload.level_3,
    )
    yaml_content = _build_yaml(
        payload.name,
        {
            "summary": write.summary,
            "description": write.description,
            "level_1": write.level_1,
            "level_2": write.level_2,
            "level_3": write.level_3,
        },
    )

    _SKILLS_ROOT.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(yaml_content + "\n")

    skill = _parse_skill(path)
    if skill is None:
        raise HTTPException(status_code=422, detail="Failed to parse created skill")
    return skill


@router.put("/{name}", response_model=SkillOut)
async def update_skill(name: str, payload: SkillWrite) -> SkillOut:
    if name == "README":
        raise HTTPException(status_code=400, detail="README is not a skill")

    data = _read_skill_dict(name)

    # Update existing data with only the provided non-empty fields.
    updates = {k: v for k, v in payload.dict().items() if v is not None}
    # Preserve the stored name; the path-derived name wins.
    data.update(updates)
    data["name"] = name

    path = _SKILLS_ROOT / f"{name}.yaml"
    yaml_content = _build_yaml(
        name,
        {
            "summary": data.get("summary"),
            "description": data.get("description"),
            "level_1": data.get("level_1"),
            "level_2": data.get("level_2"),
            "level_3": data.get("level_3"),
        },
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(yaml_content + "\n")

    skill = _parse_skill(path)
    if skill is None:
        raise HTTPException(status_code=422, detail="Failed to parse updated skill")
    return skill


@router.delete("/{name}")
async def delete_skill(name: str) -> dict:
    if name == "README":
        raise HTTPException(status_code=400, detail="README is not a skill")

    path = _SKILLS_ROOT / f"{name}.yaml"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Skill not found")
    path.unlink()
    return {"ok": True}
