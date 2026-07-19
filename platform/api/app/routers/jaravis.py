"""Jaravis chat endpoints. Non-streaming MVP: one POST runs the whole
tool-use loop and returns the reply plus a tool trace."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import jaravis

router = APIRouter(prefix="/api/jaravis", tags=["jaravis"])


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


@router.get("/status")
def status():
    return {
        "available": jaravis.available(),
        "model": jaravis.MODEL,
        "hint": None if jaravis.available() else
        "Set ANTHROPIC_API_KEY in platform/.env (or the api environment) to enable Jaravis.",
    }


@router.post("/chat")
def chat(body: ChatRequest):
    if not jaravis.available():
        raise HTTPException(503, "Jaravis is not configured — set ANTHROPIC_API_KEY for the api service.")
    if not body.messages or body.messages[-1].role != "user":
        raise HTTPException(422, "messages must end with a user message")
    msgs = [{"role": m.role, "content": m.content} for m in body.messages]
    try:
        # sync endpoint → FastAPI runs it in a threadpool; the loop may take a while
        return jaravis.run_chat(msgs)
    except Exception as e:  # surfaced to the chat UI
        raise HTTPException(502, f"Jaravis run failed: {e}") from e
