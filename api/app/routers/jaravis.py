"""Jaravis chat endpoints.

Persisted sessions (the UI): a JaravisSession holds an ordered message log that
survives page reloads, and the user can keep several in parallel.
POST /sessions/{id}/chat/stream sends one user message; the turn runs in a
BACKGROUND thread (see services.jaravis) so it survives a refresh / closed tab,
and the request just streams NDJSON progress events off the run's buffer. A
reloaded page re-attaches via GET /sessions/{id}/run/stream, and POST
/sessions/{id}/run/cancel stops an in-flight run server-side. Both turns are
persisted regardless of the client connection.

The legacy stateless endpoints are kept for scripts: /chat/stream (NDJSON) and
/chat (blocking) both take the full message array and store nothing."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..services import jaravis
from .util import audit

router = APIRouter(prefix="/api/jaravis", tags=["jaravis"])


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


class SessionRename(BaseModel):
    title: str


class SessionChatIn(BaseModel):
    content: str


@router.get("/status")
def status():
    return {
        "available": jaravis.available(),
        "model": jaravis.MODEL,
        "hint": None if jaravis.available() else
        "Set ANTHROPIC_API_KEY in .env (or the api environment) to enable Jaravis.",
    }


def _validated_messages(body: ChatRequest) -> list[dict]:
    if not jaravis.available():
        raise HTTPException(503, "Jaravis is not configured — set ANTHROPIC_API_KEY for the api service.")
    if not body.messages or body.messages[-1].role != "user":
        raise HTTPException(422, "messages must end with a user message")
    return [{"role": m.role, "content": m.content} for m in body.messages]


@router.post("/chat")
def chat(body: ChatRequest):
    msgs = _validated_messages(body)
    try:
        # sync endpoint → FastAPI runs it in a threadpool; the loop may take a while
        return jaravis.run_chat(msgs)
    except Exception as e:  # surfaced to the chat UI
        raise HTTPException(502, f"Jaravis run failed: {e}") from e


@router.post("/chat/stream")
def chat_stream(body: ChatRequest):
    """NDJSON event stream: {"type": "note"|"tool"} progress lines while the
    loop runs, then {"type": "done", reply, trace, proposals}. Errors become a
    {"type": "error"} line (the HTTP status is already 200 by then). Client
    disconnect (Stop button) closes the generator and ends the run at the
    next event boundary."""
    msgs = _validated_messages(body)

    def gen():
        try:
            for ev in jaravis.run_chat_events(msgs):
                yield json.dumps(ev) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "error": f"Jaravis run failed: {e}"}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------ chat sessions
def _session_summary(s: M.JaravisSession) -> dict:
    return {
        "id": s.id,
        "title": s.title,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
        "message_count": len(s.messages),
    }


def _message_json(m: M.JaravisMessage) -> dict:
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "trace": m.trace or [],
        "proposals": m.proposals or [],
        "created_at": m.created_at.isoformat(),
    }


@router.get("/sessions")
def list_sessions(db: Session = Depends(get_db)):
    """Chat sessions, most recently active first."""
    rows = (db.query(M.JaravisSession)
            .order_by(M.JaravisSession.updated_at.desc(), M.JaravisSession.id.desc())
            .all())
    return [_session_summary(s) for s in rows]


@router.post("/sessions")
def create_session(db: Session = Depends(get_db)):
    """Start a new empty conversation (titled from the first message on send)."""
    s = M.JaravisSession(title="New chat")
    db.add(s)
    db.flush()
    audit(db, "jaravis.session.create", "jaravis_session", s.id)
    db.commit()
    return _session_summary(s)


@router.get("/sessions/{sid}")
def get_session(sid: int, db: Session = Depends(get_db)):
    """One conversation with its full ordered message log."""
    s = db.get(M.JaravisSession, sid)
    if s is None:
        raise HTTPException(404, "session not found")
    return {**_session_summary(s), "messages": [_message_json(m) for m in s.messages]}


@router.patch("/sessions/{sid}")
def rename_session(sid: int, body: SessionRename, db: Session = Depends(get_db)):
    s = db.get(M.JaravisSession, sid)
    if s is None:
        raise HTTPException(404, "session not found")
    title = body.title.strip()
    if not title:
        raise HTTPException(422, "title must not be empty")
    s.title = title[:300]
    s.updated_at = M.utcnow()
    db.commit()
    return _session_summary(s)


@router.delete("/sessions/{sid}")
def delete_session(sid: int, db: Session = Depends(get_db)):
    s = db.get(M.JaravisSession, sid)
    if s is None:
        raise HTTPException(404, "session not found")
    db.delete(s)  # messages cascade
    audit(db, "jaravis.session.delete", "jaravis_session", sid)
    db.commit()
    return {"deleted": sid}


def _ndjson_run_stream(sid: int) -> StreamingResponse:
    """Stream a session's background run as NDJSON. Client disconnect closes
    this generator but NOT the run (it lives in its own thread)."""
    def gen():
        try:
            for ev in jaravis.stream_run_events(sid):
                yield json.dumps(ev) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "error": f"Jaravis stream failed: {e}"}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/sessions/{sid}/chat/stream")
def session_chat_stream(sid: int, body: SessionChatIn, db: Session = Depends(get_db)):
    """Start a Jaravis turn for the session and stream it. The turn runs in a
    background thread that survives this connection closing, so a refresh /
    closed tab never loses it; the user message is persisted immediately and the
    assistant reply the moment the turn completes. Same NDJSON event shape as
    /chat/stream, preceded by a {"type": "session"} event with the (possibly
    auto-generated) title. 409 if a turn is already running for this session
    (the client should attach to it instead)."""
    if not jaravis.available():
        raise HTTPException(503, "Jaravis is not configured — set ANTHROPIC_API_KEY for the api service.")
    if db.get(M.JaravisSession, sid) is None:
        raise HTTPException(404, "session not found")
    content = body.content.strip()
    if not content:
        raise HTTPException(422, "content must not be empty")
    if not jaravis.start_session_run(sid, content):
        raise HTTPException(409, "a turn is already running for this session — attach instead")
    return _ndjson_run_stream(sid)


@router.get("/sessions/{sid}/run/stream")
def attach_session_run(sid: int, db: Session = Depends(get_db)):
    """Re-attach to a session's in-flight run and replay its events from the
    start (used after a page reload). 204 if no turn is currently running — the
    stored messages are then authoritative."""
    if db.get(M.JaravisSession, sid) is None:
        raise HTTPException(404, "session not found")
    if not jaravis.has_active_run(sid):
        return Response(status_code=204)
    return _ndjson_run_stream(sid)


@router.post("/sessions/{sid}/run/cancel")
def cancel_session_run(sid: int, db: Session = Depends(get_db)):
    """Stop a session's in-flight run at the next step boundary (server-side
    Stop). Returns whether a run was actually cancelled."""
    if db.get(M.JaravisSession, sid) is None:
        raise HTTPException(404, "session not found")
    return {"cancelled": jaravis.cancel_session_run(sid)}
