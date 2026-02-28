"""
models/request.py
All incoming request schemas.
"""

from typing import Optional
from pydantic import BaseModel, Field


class AssistantRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000, description="Transcribed speech text")
    session_id: Optional[str] = Field(None, description="User/device session for memory")
    lang: str = Field("en", description="Language code e.g. 'en', 'hi', 'ar'")
    partial: bool = Field(False, description="True = interim result (don't send to LLM yet)")
    context: Optional[dict] = Field(None, description="Extra context from device (time, location)")


class StreamRequest(AssistantRequest):
    """Same as AssistantRequest but response will be SSE streamed."""
    pass
