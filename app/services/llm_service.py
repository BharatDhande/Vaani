"""
services/llm_service.py

Unified LLM client.
Supports:
  - OpenRouter  (any model via API key)
  - Self-hosted (vLLM / Ollama / LM Studio — any OpenAI-compatible endpoint)
"""

import json
import re
import time
from typing import Optional
from openai import AsyncOpenAI
from app.core.config import settings
from app.core.logger import get_logger
from app.models.response import AssistantResponse

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are AIRI Alex, a voice assistant. Reply ONLY with a JSON object. No prose, no markdown, no explanation.

Every response MUST have "intent" and "text_response" (max 15 words, what you say aloud).

Intents: open_app | make_call | send_whatsapp | send_message | send_email | set_alarm | set_timer | set_reminder | web_search | play_music | get_weather | navigate | toggle_setting | take_photo | read_notifications | llm_response

Examples:
{"intent":"llm_response","text_response":"I am doing great, thanks for asking!"}
{"intent":"open_app","app_name":"whatsapp","app_package":"com.whatsapp","text_response":"Opening WhatsApp now."}
{"intent":"make_call","contact_name":"Mom","text_response":"Calling Mom now."}
{"intent":"set_timer","timer_seconds":300,"text_response":"5 minute timer started."}
{"intent":"web_search","query":"weather today","text_response":"Searching the web for you."}

Output ONLY the JSON. Start with { and end with }. Nothing before or after."""


class LLMService:
    def __init__(self):
        self._client: Optional[AsyncOpenAI] = None

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            kwargs = {
                "api_key": settings.llm_api_key or "none",
                "base_url": settings.llm_base_url,
                "timeout": settings.LLM_TIMEOUT,
            }
            if settings.LLM_PROVIDER == "openrouter":
                kwargs["default_headers"] = {
                    "HTTP-Referer": "https://github.com/airi-alex",
                    "X-Title": "AIRI Alex Assistant",
                }
            self._client = AsyncOpenAI(**kwargs)
        return self._client

    def _build_messages(self, text: str, history: list[dict]) -> list[dict]:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        msgs.extend(history[-(settings.MEMORY_MAX_TURNS * 2):])
        msgs.append({"role": "user", "content": text})
        return msgs

    async def process(
        self,
        text: str,
        history: list[dict] | None = None,
    ) -> AssistantResponse:
        t0 = time.perf_counter()
        history = history or []
        messages = self._build_messages(text, history)

        try:
            response = await self.client.chat.completions.create(
                model=settings.llm_model,
                messages=messages,
                max_tokens=settings.LLM_MAX_TOKENS,
                temperature=settings.LLM_TEMPERATURE,
                # No response_format — most free models don't support it
                # and silently return empty content when it's set
            )

            raw = response.choices[0].message.content
            raw = raw.strip() if raw else ""
            latency_ms = int((time.perf_counter() - t0) * 1000)

            logger.info(f"LLM raw [{latency_ms}ms] model={settings.llm_model}: {repr(raw[:300])}")

            if not raw:
                logger.error(
                    "LLM returned EMPTY content. "
                    "Check: 1) OPENROUTER_API_KEY in .env  "
                    "2) Model name  3) Credits on openrouter.ai"
                )
                return AssistantResponse(
                    intent="llm_response",
                    text_response="Empty response from AI. Check API key or model name.",
                    routed_by="llm",
                    latency_ms=latency_ms,
                    error="empty_llm_response",
                )

            return self._parse_response(raw, latency_ms)

        except Exception as e:
            logger.error(f"LLM exception: {type(e).__name__}: {e}")
            return AssistantResponse(
                intent="llm_response",
                text_response="Sorry, I had trouble connecting to the AI. Please try again.",
                routed_by="llm",
                error=str(e),
            )

    def _repair_truncated_json(self, raw: str) -> str:
        """
        Repair JSON cut off by max_tokens limit.
        e.g. {"intent":"llm_response","text_response":"Hello how can I
          ->  {"intent":"llm_response","text_response":"Hello how can I"}
        """
        s = raw.strip()
        # If last char is not a closing brace or quote, we're mid-string
        if s and s[-1] not in ('"', '}'):
            s = s + '"'   # close open string value
        # Close any unclosed braces
        opens = s.count("{") - s.count("}")
        if opens > 0:
            s = s + "}" * opens
        return s

    def _parse_response(self, raw: str, latency_ms: int) -> AssistantResponse:
        """
        Parse LLM output -> AssistantResponse.
        Handles 4 cases:
          1. Clean JSON
          2. Markdown-fenced JSON  ```json {...} ```
          3. Truncated JSON cut off by max_tokens
          4. JSON buried in prose text
        """
        cleaned = raw.strip()

        # 1. Strip markdown fences
        if "```" in cleaned:
            cleaned = re.sub(r"```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"```", "", cleaned)
            cleaned = cleaned.strip()

        # 2. Direct parse
        try:
            data = json.loads(cleaned)
            return self._build_response(data, latency_ms)
        except json.JSONDecodeError:
            pass

        # 3. Repair truncated JSON (max_tokens cutoff)
        try:
            repaired = self._repair_truncated_json(cleaned)
            data = json.loads(repaired)
            logger.warning(f"Repaired truncated JSON OK: {repaired[:150]}")
            return self._build_response(data, latency_ms)
        except (json.JSONDecodeError, Exception):
            pass

        # 4. Extract first {...} block from mixed prose
        match = re.search(r"\{[^{}]*\}", cleaned, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                logger.warning(f"Extracted JSON from prose: {match.group()[:100]}")
                return self._build_response(data, latency_ms)
            except json.JSONDecodeError:
                pass

        # 5. Final fallback — raw text becomes spoken response
        logger.warning(f"All JSON parsing failed. Raw: {cleaned[:150]}")
        return AssistantResponse(
            intent="llm_response",
            text_response=cleaned[:300],
            routed_by="llm",
            latency_ms=latency_ms,
        )

    def _build_response(self, data: dict, latency_ms: int) -> AssistantResponse:
        """Build AssistantResponse from parsed dict."""
        if not data.get("text_response"):
            data["text_response"] = "Done."
        return AssistantResponse(
            routed_by="llm",
            latency_ms=latency_ms,
            **{k: v for k, v in data.items() if v is not None},
        )


# Singleton
llm_service = LLMService()