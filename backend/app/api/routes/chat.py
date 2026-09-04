"""Chat: ask the advisor, with or without a live reasoning stream."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from ...db.models import Conversation, Message
from ...db.session import get_db
from ...obs.sinks import EVENT_BUS
from ..deps import get_advisor

router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = None
    include_trace: bool = False


def _history(session: Session, conversation_id: str | None, limit: int = 8) -> list[dict]:
    if not conversation_id:
        return []
    rows = session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    ).all()
    return [{"role": m.role, "content": m.content} for m in reversed(rows)]


def _persist(session: Session, conversation_id: str, question: str, payload: dict) -> None:
    if session.get(Conversation, conversation_id) is None:
        session.add(Conversation(id=conversation_id, title=question[:200]))
    session.add(Message(conversation_id=conversation_id, role="user", content=question))
    session.add(
        Message(
            conversation_id=conversation_id,
            role="assistant",
            content=payload.get("answer", ""),
            answer_json=payload.get("structured"),
            run_id=payload.get("run_id"),
        )
    )
    session.commit()


@router.post("/chat")
def chat(body: ChatRequest, session: Session = Depends(get_db)) -> dict:
    advisor = get_advisor()
    conversation_id = body.conversation_id or f"conv_{uuid.uuid4().hex[:10]}"

    answer = advisor.ask(
        body.question,
        conversation_id=conversation_id,
        history=_history(session, body.conversation_id),
    )
    payload = answer.as_dict(include_trace=body.include_trace)
    payload["conversation_id"] = conversation_id

    try:
        _persist(session, conversation_id, body.question, payload)
    except Exception:  # noqa: BLE001 - never fail an answer over persistence
        session.rollback()
        payload["persisted"] = False

    return payload


@router.post("/chat/stream")
async def chat_stream(body: ChatRequest, request: Request) -> EventSourceResponse:
    """Stream the reasoning as it happens, then the answer.

    The trace events are the product here, not a debug feed: the controller
    watches 24 candidates get evaluated and rejected in real time, which is
    what makes the answer credible when it lands.
    """
    advisor = get_advisor()
    conversation_id = body.conversation_id or f"conv_{uuid.uuid4().hex[:10]}"
    run_id = f"run_{uuid.uuid4().hex[:12]}"

    queue = EVENT_BUS.subscribe(run_id)
    loop = asyncio.get_running_loop()
    EVENT_BUS.bind_loop(loop)

    async def generate():
        task = loop.run_in_executor(
            None,
            lambda: advisor.ask(body.question, conversation_id=conversation_id, run_id=run_id),
        )
        try:
            yield {
                "event": "start",
                "data": json.dumps({"run_id": run_id, "conversation_id": conversation_id}),
            }
            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=0.15)
                    yield {"event": message.get("event", "trace"), "data": json.dumps(message)}
                except asyncio.TimeoutError:
                    if task.done():
                        break
            answer = await task
            # Drain anything the executor emitted after the last poll.
            while not queue.empty():
                message = queue.get_nowait()
                yield {"event": message.get("event", "trace"), "data": json.dumps(message)}
            yield {
                "event": "answer",
                "data": json.dumps(
                    {**answer.as_dict(), "conversation_id": conversation_id}, default=str
                ),
            }
            yield {"event": "done", "data": json.dumps({"run_id": run_id})}
        except Exception as exc:  # noqa: BLE001
            yield {"event": "error", "data": json.dumps({"error": f"{type(exc).__name__}: {exc}"})}
        finally:
            EVENT_BUS.unsubscribe(queue, run_id)

    return EventSourceResponse(generate())


@router.get("/conversations")
def list_conversations(limit: int = 25, session: Session = Depends(get_db)) -> dict:
    rows = session.scalars(
        select(Conversation).order_by(Conversation.updated_at.desc()).limit(limit)
    ).all()
    return {
        "count": len(rows),
        "conversations": [
            {
                "id": c.id,
                "title": c.title,
                "created_at": c.created_at.isoformat(),
                "message_count": len(c.messages),
            }
            for c in rows
        ],
    }


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, session: Session = Depends(get_db)) -> dict:
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(404, f"conversation {conversation_id} not found")
    return {
        "id": conversation.id,
        "title": conversation.title,
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "structured": m.answer_json,
                "run_id": m.run_id,
                "created_at": m.created_at.isoformat(),
            }
            for m in conversation.messages
        ],
    }


@router.get("/agent/capabilities")
def capabilities() -> dict:
    """What the advisor answers, how it routes, and whether the model is live."""
    from ...agent.llm import get_client
    from ...agent.plans import catalog as plan_catalog
    from ...tools import list_tools

    advisor = get_advisor()
    return {
        "engine": advisor.engine,
        "llm": get_client().status,
        "intents": plan_catalog(),
        "tools": list_tools(),
        "boundary": {
            "llm_owns": [
                "intent classification",
                "entity proposal (validated against the dataset before use)",
                "narration of an already-computed result",
            ],
            "code_owns": [
                "every arithmetic operation",
                "every legality verdict",
                "every cost and ranking",
                "every entity existence claim",
                "the structured answer payload",
            ],
            "enforcement": (
                "Narration is checked against the run's fact ledger: any number, crew id, "
                "flight id or rule id the tools did not produce fails verification."
            ),
        },
    }
