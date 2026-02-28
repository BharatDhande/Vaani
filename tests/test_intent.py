"""
tests/test_intent.py
pytest tests for the intent router.
Run: pytest tests/ -v
"""

import pytest
from app.services.intent_router import intent_router


@pytest.mark.parametrize("text,expected_intent", [
    # App opens
    ("Open WhatsApp", "open_app"),
    ("Launch YouTube", "open_app"),
    ("Open Instagram", "open_app"),
    ("Start Spotify", "open_app"),

    # Calls
    ("Call Mom", "make_call"),
    ("Ring John please", "make_call"),
    ("Dial +1234567890", "make_call"),

    # WhatsApp
    ("WhatsApp message to Sara", "send_whatsapp"),
    ("Send WhatsApp to David", "send_whatsapp"),

    # SMS
    ("Send SMS to Mike", "send_message"),
    ("Text message to Alice", "send_message"),

    # Alarm
    ("Set alarm for 7 AM", "set_alarm"),
    ("Wake me at 6:30", "set_alarm"),
    ("Alarm at 8", "set_alarm"),

    # Timer
    ("Set timer for 5 minutes", "set_timer"),
    ("Start timer for 2 hours 30 minutes", "set_timer"),
    ("Countdown 90 seconds", "set_timer"),

    # Reminder
    ("Remind me to take medicine at 9 PM", "set_reminder"),
    ("Set reminder to call boss", "set_reminder"),

    # Navigate
    ("Navigate to Mumbai", "navigate"),
    ("Directions to airport", "navigate"),
    ("Take me to the nearest hospital", "navigate"),

    # Weather
    ("What's the weather today", "get_weather"),
    ("Temperature in Delhi", "get_weather"),

    # Search
    ("Search for best Python tutorials", "web_search"),
    ("Google latest news", "web_search"),

    # Music
    ("Play Bollywood music", "play_music"),
    ("Play Shape of You", "play_music"),

    # Toggle
    ("Turn on WiFi", "toggle_setting"),
    ("Turn off Bluetooth", "toggle_setting"),
    ("Enable flashlight", "toggle_setting"),

    # Photo
    ("Take a photo", "take_photo"),
    ("Open camera", "take_photo"),

    # Notifications
    ("Read my notifications", "read_notifications"),

    # Should go to LLM (returns None)
    ("What is the capital of France?", None),
    ("Tell me a joke", None),
    ("How are you?", None),
])
def test_intent_routing(text: str, expected_intent):
    result = intent_router.route(text)
    if expected_intent is None:
        assert result is None, f"Expected None for '{text}', got {result}"
    else:
        assert result is not None, f"Expected {expected_intent} for '{text}', got None"
        assert result.intent == expected_intent, (
            f"'{text}' → expected={expected_intent}, got={result.intent}"
        )


def test_timer_extraction():
    result = intent_router.route("Set timer for 2 hours 30 minutes")
    assert result is not None
    assert result.timer_seconds == 9000  # 2*3600 + 30*60


def test_app_package_extraction():
    result = intent_router.route("Open WhatsApp")
    assert result is not None
    assert result.app_name == "whatsapp"
    assert result.app_package == "com.whatsapp"


def test_contact_extraction():
    result = intent_router.route("Call John please")
    assert result is not None
    assert result.contact_name == "John"
