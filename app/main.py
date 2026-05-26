import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.limiter import limiter
from app.schemas.base import ErrorDetail, ErrorResponse

_logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    from app.workers.tasks import procrastinate_app
    async with procrastinate_app.open_async():
        yield


def create_app() -> FastAPI:
    app: FastAPI = FastAPI(
        title="RNA-Seq DEG API",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=_lifespan,
    )

    origins = settings.origins
    if "*" in origins:
        _logger.warning(
            "ALLOWED_ORIGINS='*' is incompatible with allow_credentials=True. Overriding to empty list."
        )
        origins = []

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "PATCH"],
        allow_headers=["Authorization", "X-API-Key", "Content-Type"],
    )

    app.state.limiter = limiter

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content=ErrorResponse(
                error=ErrorDetail(code="RATE_LIMIT_EXCEEDED", message="Too many requests.")
            ).model_dump(),
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            content = ErrorResponse(error=ErrorDetail(**exc.detail)).model_dump()
        else:
            content = ErrorResponse(error=ErrorDetail(code=str(exc.status_code), message=str(exc.detail))).model_dump()
        return JSONResponse(status_code=exc.status_code, content=content)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        _logger.exception("Unhandled exception on %s %s", request.method, request.url, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(error=ErrorDetail(code="INTERNAL_ERROR", message="An unexpected error occurred.")).model_dump(),
        )

    from app.routers import auth, files, health, jobs, results, users
    
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(files.router, prefix="/api/v1")
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(jobs.router, prefix="/api/v1")
    app.include_router(results.router, prefix="/api/v1")
    app.include_router(users.router, prefix="/api/v1")

    return app


app = create_app()
