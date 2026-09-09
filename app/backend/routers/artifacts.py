"""HTTP API for the durable generated-artifact registry."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.backend.services.artifacts import (
    delete_artifact,
    get_artifact,
    get_versions,
    list_artifacts,
    link_artifact_to_source,
    register_artifact,
)

router = APIRouter(prefix="/artifacts")


class RegisterArtifactRequest(BaseModel):
    path: str
    source_agent: str = "generated"
    source_task: Optional[str] = None
    source_session: Optional[str] = None
    parent_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LinkArtifactSourceRequest(BaseModel):
    source_file_id: str
    source_file_name: str


def _public(record: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id", "name", "path", "kind", "mime", "size", "sha256", "version",
        "source_agent", "source_task", "source_session", "created_at", "updated_at",
        "parent_id", "metadata",
    )
    return {key: record.get(key) for key in keys}


@router.get("")
async def list_artifact_records(
    source_agent: Optional[str] = Query(default=None),
    kind: Optional[str] = Query(default=None),
    session: Optional[str] = Query(default=None),
):
    artifacts = [_public(record) for record in list_artifacts(source_agent, kind, session)]
    return {"artifacts": artifacts, "count": len(artifacts)}


@router.get("/{artifact_id}")
async def artifact_detail(artifact_id: str):
    record = get_artifact(artifact_id)
    if not record:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return record


@router.get("/{artifact_id}/versions")
async def artifact_versions(artifact_id: str):
    if not get_artifact(artifact_id):
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {"artifact_id": artifact_id, "versions": get_versions(artifact_id)}


@router.post("/{artifact_id}/link-source")
async def link_artifact_source(artifact_id: str, request: LinkArtifactSourceRequest):
    record = link_artifact_to_source(
        artifact_id,
        request.source_file_id,
        request.source_file_name,
    )
    if not record:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return record


@router.delete("/{artifact_id}")
async def delete_artifact_record(artifact_id: str):
    if not delete_artifact(artifact_id):
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {"deleted": artifact_id}


@router.post("/register")
async def register_artifact_record(request: RegisterArtifactRequest):
    try:
        return register_artifact(
            request.path,
            source_agent=request.source_agent,
            source_task=request.source_task,
            source_session=request.source_session,
            parent_id=request.parent_id,
            metadata=request.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
