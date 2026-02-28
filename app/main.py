"""
main.py
FastAPI application entry point for AIRI Alex Backend.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
import time

from app.core.config import settings
from app.core.logger import get_logger
from app.routers import assistant, stream, health

logger = get_logger(__name__)


# ── Lifespan ───────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION} starting")
    logger.info(f"   LLM Provider : {settings.LLM_PROVIDER}")
    logger.info(f"   LLM Model    : {settings.llm_model}")
    logger.info(f"   LLM Base URL : {settings.llm_base_url}")
    logger.info(f"   Memory       : {'Redis' if settings.USE_REDIS else 'In-Memory'}")
    yield
    logger.info("Shutting down AIRI Alex backend")


# ── App ────────────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI Voice Assistant Backend — OpenRouter + Self-hosted LLM",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── Middleware ─────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.middleware("http")
async def add_latency_header(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    ms = int((time.perf_counter() - t0) * 1000)
    response.headers["X-Latency-Ms"] = str(ms)
    return response


# ── Global exception handler ───────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )


# ── Routers ────────────────────────────────────────────────────────────────
app.include_router(health.router)
app.include_router(assistant.router)
app.include_router(stream.router)


# ── Dev run ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="debug" if settings.DEBUG else "info",
        workers=1,  # use gunicorn for multi-worker in prod
    )
