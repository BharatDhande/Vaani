"""
services/intent_router.py

Fast rule-based intent router.
Runs BEFORE LLM — handles ~90% of commands in < 5ms.

Pattern priority: first match wins.
Each pattern returns a partial AssistantResponse dict
that gets merged with extracted entities.
"""

import re
from dataclasses import dataclass, field
from typing import Callable, Optional
from app.models.response import AssistantResponse, IntentType
from app.core.logger import get_logger

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# App name → Android package map (extend as needed)
# ─────────────────────────────────────────────────────────────────────────────
APP_PACKAGES: dict[str, str] = {
    "whatsapp": "com.whatsapp",
    "instagram": "com.instagram.android",
    "youtube": "com.google.android.youtube",
    "maps": "com.google.android.apps.maps",
    "google maps": "com.google.android.apps.maps",
    "spotify": "com.spotify.music",
    "netflix": "com.netflix.mediaclient",
    "telegram": "org.telegram.messenger",
    "twitter": "com.twitter.android",
    "x": "com.twitter.android",
    "facebook": "com.facebook.katana",
    "snapchat": "com.snapchat.android",
    "gmail": "com.google.android.gm",
    "camera": "android.media.action.IMAGE_CAPTURE",
    "calculator": "com.android.calculator2",
    "settings": "com.android.settings",
    "chrome": "com.android.chrome",
    "clock": "com.android.deskclock",
    "contacts": "com.android.contacts",
    "phone": "com.android.dialer",
    "photos": "com.google.android.apps.photos",
    "play store": "com.android.vending",
    "files": "com.google.android.documentsui",
    "tiktok": "com.zhiliaoapp.musically",
    "linkedin": "com.linkedin.android",
    "zoom": "us.zoom.videomeetings",
    "uber": "com.ubercab",
}

TOGGLE_SETTINGS: set[str] = {
    "wifi", "wi-fi", "bluetooth", "flashlight", "torch",
    "airplane mode", "do not disturb", "hotspot", "dark mode",
    "rotation", "silent", "vibration",
}


# ─────────────────────────────────────────────────────────────────────────────
# Helper extractors
# ─────────────────────────────────────────────────────────────────────────────

def _extract_app_name(text: str) -> tuple[Optional[str], Optional[str]]:
    """Returns (app_name, package_name) or (None, None)."""
    text_lower = text.lower()
    # longest match first
    for app, pkg in sorted(APP_PACKAGES.items(), key=lambda x: -len(x[0])):
        if app in text_lower:
            return app, pkg
    # fallback: grab word after trigger
    m = re.search(r"(?:open|launch|start|run)\s+(\w[\w\s]*?)(?:\s+app)?$", text_lower)
    if m:
        name = m.group(1).strip()
        return name, APP_PACKAGES.get(name)
    return None, None


def _extract_contact(text: str) -> Optional[str]:
    m = re.search(
        r"(?:call|message|text|whatsapp|ring|dial|ping)\s+(?:to\s+)?([A-Za-z][A-Za-z\s]{1,30}?)(?:\s+(?:and|please|now|on|via)|\.|$)",
        text, re.IGNORECASE,
    )
    return m.group(1).strip() if m else None


def _extract_time(text: str) -> Optional[str]:
    m = re.search(r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b", text, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _extract_timer_seconds(text: str) -> Optional[int]:
    total = 0
    for val, unit in re.findall(r"(\d+)\s*(hour|hr|minute|min|second|sec)", text, re.IGNORECASE):
        v = int(val)
        u = unit.lower()
        if u.startswith("h"):
            total += v * 3600
        elif u.startswith("m"):
            total += v * 60
        else:
            total += v
    return total if total else None


def _extract_query(text: str, triggers: list[str]) -> Optional[str]:
    text_lower = text.lower()
    for t in triggers:
        idx = text_lower.find(t)
        if idx != -1:
            q = text[idx + len(t):].strip(" ?.,")
            return q if q else None
    return None


def _extract_setting(text: str) -> Optional[str]:
    text_lower = text.lower()
    for s in TOGGLE_SETTINGS:
        if s in text_lower:
            return s
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Rule definition
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class IntentRule:
    name: str
    intent: IntentType
    keywords: list[str]                    # ANY of these trigger a match
    negative_keywords: list[str] = field(default_factory=list)  # must NOT appear
    extractor: Optional[Callable] = None   # returns dict to merge into response
    priority: int = 0                      # higher = checked first


def _build_rules() -> list[IntentRule]:
    return sorted([
        # ── App control ──────────────────────────────────────────────────────
        IntentRule(
            name="open_app",
            intent="open_app",
            keywords=["open ", "launch ", "start ", "run "],
            negative_keywords=["search", "look up", "find"],
            extractor=lambda t: {
                "app_name": _extract_app_name(t)[0],
                "app_package": _extract_app_name(t)[1],
                "text_response": f"Opening {_extract_app_name(t)[0] or 'app'}",
            },
            priority=10,
        ),

        # ── Calls ────────────────────────────────────────────────────────────
        IntentRule(
            name="make_call",
            intent="make_call",
            keywords=["call ", "ring ", "dial ", "phone "],
            negative_keywords=["reminder", "schedule", "whatsapp call"],
            extractor=lambda t: {
                "contact_name": _extract_contact(t),
                "text_response": f"Calling {_extract_contact(t) or 'contact'}",
            },
            priority=9,
        ),

        # ── WhatsApp message ─────────────────────────────────────────────────
        IntentRule(
            name="send_whatsapp",
            intent="send_whatsapp",
            keywords=["whatsapp ", "send whatsapp", "message on whatsapp"],
            extractor=lambda t: {
                "contact_name": _extract_contact(t),
                "text_response": "Opening WhatsApp",
            },
            priority=11,
        ),

        # ── SMS ──────────────────────────────────────────────────────────────
        IntentRule(
            name="send_message",
            intent="send_message",
            keywords=["send message", "text message", "sms ", "send sms"],
            extractor=lambda t: {
                "contact_name": _extract_contact(t),
                "text_response": f"Sending message to {_extract_contact(t) or 'contact'}",
            },
            priority=8,
        ),

        # ── Email ────────────────────────────────────────────────────────────
        IntentRule(
            name="send_email",
            intent="send_email",
            keywords=["send email", "compose email", "email to", "send mail"],
            extractor=lambda t: {
                "contact_name": _extract_contact(t),
                "text_response": "Opening email composer",
            },
            priority=8,
        ),

        # ── Alarm ────────────────────────────────────────────────────────────
        IntentRule(
            name="set_alarm",
            intent="set_alarm",
            keywords=["set alarm", "wake me", "alarm at", "alarm for"],
            extractor=lambda t: {
                "alarm_time": _extract_time(t),
                "text_response": f"Setting alarm for {_extract_time(t) or 'specified time'}",
            },
            priority=9,
        ),

        # ── Timer ────────────────────────────────────────────────────────────
        IntentRule(
            name="set_timer",
            intent="set_timer",
            keywords=["set timer", "start timer", "timer for", "countdown"],
            extractor=lambda t: {
                "timer_seconds": _extract_timer_seconds(t),
                "text_response": "Timer started",
            },
            priority=9,
        ),

        # ── Reminder ─────────────────────────────────────────────────────────
        IntentRule(
            name="set_reminder",
            intent="set_reminder",
            keywords=["remind me", "set reminder", "reminder to", "don't let me forget"],
            extractor=lambda t: {
                "reminder_text": t,
                "reminder_time": _extract_time(t),
                "text_response": "Reminder set",
            },
            priority=8,
        ),

        # ── Navigation ───────────────────────────────────────────────────────
        IntentRule(
            name="navigate",
            intent="navigate",
            keywords=["navigate to", "directions to", "take me to", "how to reach", "route to"],
            extractor=lambda t: {
                "location": _extract_query(t, ["navigate to", "directions to", "take me to", "route to", "how to reach"]),
                "text_response": "Opening navigation",
            },
            priority=9,
        ),

        # ── Weather ──────────────────────────────────────────────────────────
        IntentRule(
            name="get_weather",
            intent="get_weather",
            keywords=["weather", "temperature", "forecast", "rain today", "will it rain"],
            extractor=lambda t: {
                "query": _extract_query(t, ["weather in", "weather for", "weather at"]) or "current location",
                "text_response": "Fetching weather",
            },
            priority=7,
        ),

        # ── Web search ───────────────────────────────────────────────────────
        IntentRule(
            name="web_search",
            intent="web_search",
            keywords=["search for", "google ", "search ", "look up", "find me", "browse"],
            extractor=lambda t: {
                "query": _extract_query(t, ["search for", "google", "search", "look up", "find me", "browse"]),
                "text_response": "Searching the web",
            },
            priority=6,
        ),

        # ── Music ────────────────────────────────────────────────────────────
        IntentRule(
            name="play_music",
            intent="play_music",
            keywords=["play music", "play song", "play ", "pause music", "next song", "previous song", "stop music"],
            extractor=lambda t: {
                "query": _extract_query(t, ["play "]),
                "text_response": "Playing music",
            },
            priority=7,
        ),

        # ── Toggle settings ──────────────────────────────────────────────────
        IntentRule(
            name="toggle_setting",
            intent="toggle_setting",
            keywords=["turn on", "turn off", "enable ", "disable ", "toggle ", "switch on", "switch off"],
            extractor=lambda t: {
                "setting_name": _extract_setting(t),
                "setting_value": any(w in t.lower() for w in ["on", "enable", "switch on"]),
                "text_response": f"Toggling {_extract_setting(t) or 'setting'}",
            },
            priority=8,
        ),

        # ── Camera ───────────────────────────────────────────────────────────
        IntentRule(
            name="take_photo",
            intent="take_photo",
            keywords=["take photo", "take picture", "take selfie", "open camera", "click photo"],
            extractor=lambda t: {"text_response": "Opening camera"},
            priority=9,
        ),

        # ── Notifications ────────────────────────────────────────────────────
        IntentRule(
            name="read_notifications",
            intent="read_notifications",
            keywords=["read notifications", "show notifications", "what are my notifications", "any messages"],
            extractor=lambda t: {"text_response": "Reading your notifications"},
            priority=7,
        ),

    ], key=lambda r: -r.priority)


RULES = _build_rules()


# ─────────────────────────────────────────────────────────────────────────────
# Public router function
# ─────────────────────────────────────────────────────────────────────────────

class IntentRouter:
    """
    Call route(text) → returns AssistantResponse or None.
    None means: send to LLM.
    """

    def __init__(self):
        self.rules = RULES

    def route(self, text: str) -> Optional[AssistantResponse]:
        text_lower = text.lower()

        for rule in self.rules:
            # Check negative keywords first
            if any(neg in text_lower for neg in rule.negative_keywords):
                continue

            # Check if ANY keyword matches
            if not any(kw in text_lower for kw in rule.keywords):
                continue

            # Matched — extract entities
            extra = rule.extractor(text) if rule.extractor else {}

            logger.debug(f"Rule matched: {rule.name} | text='{text[:60]}'")

            return AssistantResponse(
                intent=rule.intent,
                confidence=1.0,
                routed_by="rule",
                **extra,
            )

        logger.debug(f"No rule matched for: '{text[:60]}' → sending to LLM")
        return None


# Singleton
intent_router = IntentRouter()
