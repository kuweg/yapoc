from fastapi import APIRouter

router = APIRouter(prefix="/api")


@router.get("/test")
async def test_endpoint():
    """Simple test endpoint — returns {"status": "ok"}."""
    return {"status": "ok"}
