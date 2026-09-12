"""Explicit user-driven comparisons; ordinary task APIs are unchanged."""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from app.backend.services import universes
from app.utils.tools import shell_arguments

router = APIRouter(prefix='/universes', tags=['universes'])


class Launch(BaseModel):
    objective: str = Field(min_length=3, max_length=6000)
    requirements: str = Field(default='', max_length=6000)
    approaches: list[str] = Field(min_length=2, max_length=2)
    session_id: str = Field(min_length=1, max_length=200)
    minutes: int = Field(default=15, ge=1, le=60)
    budget_usd: float = Field(default=2, ge=0.1, le=100, allow_inf_nan=False)
    check_command: str = Field(default='npm --prefix app/frontend run build', min_length=1, max_length=1000)

    @field_validator('approaches')
    @classmethod
    def approaches_valid(cls, values):
        if any(not v.strip() or len(v) > 2000 for v in values): raise ValueError('Describe both approaches.')
        return values

    @field_validator('check_command')
    @classmethod
    def check_valid(cls, value):
        if not shell_arguments(value): raise ValueError('Use one check command without shell operators.')
        return value


async def call(fn, *args):
    try: return await fn(*args)
    except FileNotFoundError: raise HTTPException(404, 'Comparison not found.') from None
    except ValueError as exc: raise HTTPException(409, str(exc)) from None
    except Exception: raise HTTPException(503, 'Parallel execution is unavailable. Check Git and Linux isolation prerequisites.') from None


@router.get('')
async def list_comparisons(session_id: str | None = Query(None)):
    return universes.listing(session_id)


@router.post('')
async def launch(request: Launch):
    return await call(universes.create, request)


@router.get('/{mid}')
async def get(mid: str):
    try: return universes.read(mid)
    except (FileNotFoundError, ValueError): raise HTTPException(404, 'Comparison not found.') from None


@router.post('/{mid}/stop')
async def stop_all(mid: str):
    return await call(universes.stop, mid)


@router.post('/{mid}/discard')
async def discard(mid: str):
    return await call(universes.discard, mid)


@router.delete('/{mid}')
async def cleanup(mid: str):
    return await call(universes.cleanup, mid)


@router.post('/{mid}/{letter}/stop')
async def stop_one(mid: str, letter: str):
    return await call(universes.stop, mid, letter)


@router.post('/{mid}/{letter}/choose')
async def choose(mid: str, letter: str):
    return await call(universes.integrate, mid, letter)


@router.get('/{mid}/{letter}/changes')
async def changes(mid: str, letter: str):
    return await call(universes.changes, mid, letter)


@router.get('/{mid}/{letter}/activity')
async def activity(mid: str, letter: str):
    try: return universes.activity(mid, letter)
    except ValueError: raise HTTPException(404, 'Run not found.') from None


@router.post('/{mid}/{letter}/preview')
async def preview(mid: str, letter: str):
    try: return universes.open_preview(mid, letter)
    except (OSError, ValueError): raise HTTPException(409, 'Preview is not available for this run.') from None
