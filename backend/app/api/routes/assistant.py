from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_operator, require_password_set
from app.core.database import get_db
from app.models.user import User
from app.services import audit
from app.services.ai_assistant_service import AssistantUnavailableError, chat
from app.services.runtime_settings import get_effective

router = APIRouter(prefix="/api/assistant", tags=["assistant"], dependencies=[Depends(require_password_set)])


class ChatTurn(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatTurn] = []


class ChatResponse(BaseModel):
    reply: str
    # When set, matches POST /api/scripts/run's request body (minus
    # `explanation`) - the frontend shows it as a confirm card and, only on
    # explicit click, re-posts these same fields to that endpoint.
    proposed_action: dict | None = None


@router.post("/chat", response_model=ChatResponse)
async def assistant_chat(
    payload: ChatRequest,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    settings = await get_effective(db)
    try:
        result = await chat(db, payload.message, [t.model_dump() for t in payload.history], settings)
    except AssistantUnavailableError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if result.get("proposed_action"):
        await audit.record(
            db, user.username, "assistant_proposed_script",
            details=str(result["proposed_action"])[:500],
        )
    return result
