"""
main.py
FastAPI application — VAANI AI Assistant Backend
Production-grade, OpenRouter + Self-hosted LLM support
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import time
import asyncio

from app.core.config import settings
from app.core.logger import get_logger
from app.routers import assistant, stream, health

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# LIFESPAN
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info(f"  🚀  {settings.APP_NAME}  v{settings.APP_VERSION}")
    logger.info("=" * 60)
    logger.info(f"  LLM Provider  : {settings.LLM_PROVIDER}")
    logger.info(f"  LLM Model     : {settings.llm_model}")
    logger.info(f"  LLM Base URL  : {settings.llm_base_url}")
    logger.info(f"  Memory        : {'Redis' if settings.USE_REDIS else 'In-Memory'}")
    logger.info(f"  Host          : {settings.HOST}:{settings.PORT}")
    logger.info(f"  Debug         : {settings.DEBUG}")
    logger.info("=" * 60)

    yield

    logger.info("🔴 Shutting down VAANI backend...")


# ─────────────────────────────────────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "VAANI — AI Voice Assistant Backend\n\n"
        "Supports OpenRouter, OpenAI, and self-hosted LLM endpoints.\n"
        "Real-time streaming, memory, and multi-turn conversation."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


# ─────────────────────────────────────────────────────────────────────────────
# MIDDLEWARE
# ─────────────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Log every request with method, path, status, and latency."""
    t0 = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    response.headers["X-Latency-Ms"] = str(elapsed_ms)
    response.headers["X-Powered-By"] = "VAANI"

    log_level = "warning" if response.status_code >= 400 else "info"
    getattr(logger, log_level)(
        f"{request.method} {request.url.path} → {response.status_code} [{elapsed_ms}ms]"
    )

    return response


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Basic in-memory rate limiter (extend with Redis for production)."""
    # Placeholder — swap out for slowapi or Redis-based limiter
    return await call_next(request)


# ─────────────────────────────────────────────────────────────────────────────
# EXCEPTION HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code,
            "path": str(request.url.path),
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc) if settings.DEBUG else "Something went wrong.",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# ROUTERS
# ─────────────────────────────────────────────────────────────────────────────

app.include_router(health.router, tags=["Health"])
app.include_router(assistant.router, prefix="/assistant", tags=["Assistant"])
app.include_router(stream.router, prefix="/stream", tags=["Streaming"])


# ─────────────────────────────────────────────────────────────────────────────
# ROOT
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/", tags=["Root"])
async def root():
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "online",
        "docs": "/docs",
    }


# ─────────────────────────────────────────────────────────────────────────────
# DEV RUN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="debug" if settings.DEBUG else "info",
        workers=1,
        access_log=False,  # handled by our middleware
    )