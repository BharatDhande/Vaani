"""
routers/assistant.py

Main POST /process endpoint.
Orchestration flow:
  1. Validate input
  2. Check API key (if enabled)
  3. Run intent router (< 5ms)
  4. If no match → LLM
  5. Save to memory
  6. Return AssistantResponse JSON
"""

import time
import json
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.security.api_key import APIKeyHeader

from app.models.request import AssistantRequest
from app.models.response import AssistantResponse
from app.services.intent_router import intent_router
from app.services.llm_service import llm_service
from app.services.memory_service import memory_service
from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["assistant"])

# ── Optional API key auth ──────────────────────────────────────────────────
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Depends(api_key_header)):
    if settings.REQUIRE_API_KEY:
        if not api_key or api_key != settings.API_KEY:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return api_key


# ── Main endpoint ──────────────────────────────────────────────────────────

@router.post("/process", response_model=AssistantResponse)
async def process(
    req: AssistantRequest,
    _: str = Depends(verify_api_key),
):
    """
    Core assistant endpoint.
    Flutter sends speech text here, gets back a JSON action.
    """
    t0 = time.perf_counter()

    # Partial results = interim STT transcript; skip LLM, just echo
    if req.partial:
        return AssistantResponse(
            intent="unknown",
            text_response=None,
            routed_by="rule",
        )

    text = req.text.strip()
    logger.info(f"[{req.session_id or 'anon'}] Processing: '{text[:80]}'")

    # ── Step 1: Fast rule router ────────────────────────────────────────────
    response = intent_router.route(text)

    # ── Step 2: LLM fallback ────────────────────────────────────────────────
    if response is None:
        history = await memory_service.get_history(req.session_id or "")
        response = await llm_service.process(text, history)

    # ── Step 3: Attach latency ──────────────────────────────────────────────
    response.latency_ms = int((time.perf_counter() - t0) * 1000)
    logger.info(f"[{req.session_id or 'anon'}] Intent={response.intent} | {response.latency_ms}ms | routed_by={response.routed_by}")

    # ── Step 4: Save to memory ──────────────────────────────────────────────
    if req.session_id:
        await memory_service.append(
            req.session_id,
            text,
            response.model_dump_json(),
        )

    return response


@router.delete("/memory/{session_id}")
async def clear_memory(session_id: str, _: str = Depends(verify_api_key)):
    """Clear conversation history for a session."""
    await memory_service.clear(session_id)
    return {"status": "cleared", "session_id": session_id}
