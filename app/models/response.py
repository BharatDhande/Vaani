"""
models/response.py
All outgoing response schemas.
Flutter reads these and acts on them.
"""

from typing import Optional, Any, Literal
from pydantic import BaseModel


# ── Intent types Flutter will handle ─────────────────────────────────────────
IntentType = Literal[
    "open_app",
    "make_call",
    "send_message",
    "send_whatsapp",
    "send_email",
    "set_alarm",
    "set_timer",
    "set_reminder",
    "web_search",
    "play_music",
    "get_weather",
    "get_news",
    "navigate",
    "take_photo",
    "toggle_setting",     # wifi, bluetooth, flashlight etc.
    "read_notifications",
    "llm_response",       # general answer from LLM
    "unknown",
]


class AssistantResponse(BaseModel):
    intent: IntentType
    confidence: float = 1.0

    # ── Action payload (intent-specific) ─────────────────────────────────────
    app_name: Optional[str] = None          # open_app
    app_package: Optional[str] = None       # open_app (android package name)
    phone_number: Optional[str] = None      # make_call / send_message
    contact_name: Optional[str] = None      # make_call / send_message
    message_body: Optional[str] = None      # send_message / send_whatsapp / email
    email_to: Optional[str] = None          # send_email
    email_subject: Optional[str] = None     # send_email
    alarm_time: Optional[str] = None        # set_alarm  (ISO 8601 or "HH:MM")
    timer_seconds: Optional[int] = None     # set_timer
    reminder_text: Optional[str] = None     # set_reminder
    reminder_time: Optional[str] = None     # set_reminder
    query: Optional[str] = None             # web_search / get_weather / get_news
    location: Optional[str] = None          # navigate / get_weather
    setting_name: Optional[str] = None      # toggle_setting
    setting_value: Optional[bool] = None    # toggle_setting

    # ── LLM general response ──────────────────────────────────────────────────
    text_response: Optional[str] = None     # what the assistant should say aloud

    # ── Metadata ──────────────────────────────────────────────────────────────
    routed_by: Literal["rule", "llm"] = "rule"
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    extra: Optional[dict[str, Any]] = None  # forward-compatible extras


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    llm_provider: str
    llm_model: str
