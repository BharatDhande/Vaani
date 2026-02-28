"""
routers/stream.py

Server-Sent Events (SSE) endpoint for streaming LLM responses.
Flutter listens via HTTP EventSource / SSE package.

Flow:
  1. Rule router → instant done event (< 5ms)
  2. LLM fallback → call process(), then stream text_response word-by-word
     (JSON-output models can't be reliably streamed as raw tokens)
"""

import json
import asyncio
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.models.request import StreamRequest
from app.services.intent_router import intent_router
from app.services.llm_service import llm_service
from app.services.memory_service import memory_service
from app.core.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["stream"])


async def _sse_generator(req: StreamRequest):
    """
    SSE event types Flutter receives:
      data: {"type":"thinking"}                          ← LLM is working
      data: {"type":"token","value":"Hello "}            ← word-by-word
      data: {"type":"done","intent":"...","text_response":"...","routed_by":"..."}
    """
    text = req.text.strip()

    # ── Step 1: Fast rule router ────────────────────────────────────────────
    response = intent_router.route(text)
    if response:
        payload = json.dumps({"type": "done", **response.model_dump()})
        yield f"data: {payload}\n\n"
        return

    # ── Step 2: LLM — signal thinking immediately so Flutter shows spinner ──
    yield f"data: {json.dumps({'type': 'thinking'})}\n\n"
    await asyncio.sleep(0)

    # ── Step 3: Call LLM (non-streaming — JSON output is reliable) ──────────
    history = await memory_service.get_history(req.session_id or "")
    response = await llm_service.process(text, history)

    spoken = response.text_response or ""

    # ── Step 4: Stream text_response word-by-word so UI feels live ──────────
    if spoken:
        words = spoken.split(" ")
        for i, word in enumerate(words):
            # Re-add space between words (except last)
            value = word if i == len(words) - 1 else word + " "
            token_payload = json.dumps({"type": "token", "value": value})
            yield f"data: {token_payload}\n\n"
            await asyncio.sleep(0.04)   # ~25 words/sec — feels natural

    # ── Step 5: Final done event with full structured response ───────────────
    done_payload = json.dumps({
        "type": "done",
        **response.model_dump(),
    })
    yield f"data: {done_payload}\n\n"

    # ── Step 6: Save to memory ───────────────────────────────────────────────
    if req.session_id:
        await memory_service.append(
            req.session_id,
            text,
            response.model_dump_json(),
        )


@router.post("/stream")
async def stream_process(req: StreamRequest):
    """
    SSE streaming endpoint.
    Content-Type: text/event-stream
    """
    return StreamingResponse(
        _sse_generator(req),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )