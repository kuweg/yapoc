"""PPTX presentation viewing endpoint."""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.backend.services import pptx_view

router = APIRouter(prefix="/pptx")


@router.get("/view")
def view_pptx(
    upload_id: Optional[str] = Query(default=None),
    path: Optional[str] = Query(default=None),
) -> FileResponse:
    """Convert a permitted PPTX source to PDF and serve it inline."""
    if bool(upload_id) == bool(path):
        raise HTTPException(status_code=400, detail="Provide either upload_id or path")

    try:
        src = (
            pptx_view.resolve_upload_source(upload_id)
            if upload_id
            else pptx_view.resolve_generated_source(path or "")
        )
        pdf = pptx_view.convert_pptx_to_pdf(src)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return FileResponse(str(pdf), media_type="application/pdf", filename=None)
