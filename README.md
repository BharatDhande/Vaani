# Vaani - AI Assistant Backend

## Project Structure
```
Vaani-backend/
├── app/
│   ├── main.py                  # FastAPI app entry point
│   ├── core/
│   │   ├── config.py            # All settings & env vars
│   │   └── logger.py            # Structured logging
│   ├── models/
│   │   ├── request.py           # Pydantic request models
│   │   └── response.py          # Pydantic response models
│   ├── routers/
│   │   ├── assistant.py         # Main /process endpoint
│   │   ├── health.py            # Health check endpoint
│   │   └── stream.py            # SSE streaming endpoint
│   ├── services/
│   │   ├── intent_router.py     # Fast rule-based router
│   │   ├── llm_service.py       # OpenRouter + self-hosted LLM
│   │   ├── memory_service.py    # Conversation memory
│   │   └── tts_service.py       # Text-to-speech (optional)
│   └── handlers/
│       ├── app_handler.py       # Open app intents
│       ├── call_handler.py      # Call/message intents
│       ├── search_handler.py    # Search intents
│       ├── alarm_handler.py     # Alarm/timer intents
│       └── llm_handler.py       # Complex LLM fallback
├── tests/
│   └── test_intent.py
├── .env.example
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

## Quick Start
```bash
cp .env.example .env
# Edit .env with your API keys
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Performance Targets
- Intent detection: < 200ms
- Simple commands: < 300ms  
- LLM response: < 800ms
- Total E2E: ~1–1.5 seconds
