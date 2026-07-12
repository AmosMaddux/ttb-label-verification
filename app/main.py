"""FastAPI application entry point for the TTB Label Verification POC.

This module wires together the API routes, static frontend assets, and the
small health/index endpoints used by local checks and deployment readiness.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.verify import _get_cached_vision_service, router as verify_router
from app.vision.model_check import validate_configured_model_if_enabled


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


async def validate_startup_vision_model() -> None:
    """Fail fast when the configured live vision model is unavailable."""
    await validate_configured_model_if_enabled()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Run startup checks before serving traffic."""
    await validate_startup_vision_model()
    try:
        yield
    finally:
        await close_cached_vision_service()


async def close_cached_vision_service() -> None:
    """Close and clear the cached vision service if it has been created."""
    if _get_cached_vision_service.cache_info().currsize == 0:
        return

    service = _get_cached_vision_service()
    try:
        await _close_if_supported(service.client)
    finally:
        _get_cached_vision_service.cache_clear()


async def _close_if_supported(client: object) -> None:
    for method_name in ("aclose", "close"):
        close = getattr(client, method_name, None)
        if callable(close):
            result = close()
            if hasattr(result, "__await__"):
                await result
            return


app = FastAPI(title="TTB Label Verification POC", lifespan=lifespan)
app.include_router(verify_router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health() -> dict[str, str]:
    """Return a lightweight service-health response.

    Inputs:
        None. The route does not inspect request body, auth, or external
        services.

    Outputs:
        A small JSON-serializable dictionary. `{"status": "ok"}` means the
        FastAPI process is alive and able to serve requests.
    """
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
@app.head("/", include_in_schema=False)
def index() -> FileResponse:
    """Serve the browser UI shell.

    Inputs:
        None directly. FastAPI invokes this for `GET /` and `HEAD /`.

    Outputs:
        A `FileResponse` pointing at `app/static/index.html`.
    """
    return FileResponse(STATIC_DIR / "index.html")
