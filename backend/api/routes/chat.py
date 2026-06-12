from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from db.database import get_db
from api.services.llm_service import get_ai_response
from api.deps import get_current_user, limiter
from db.models import User
from fastapi import Request

router = APIRouter()

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    reply: str

@router.post("/", response_model=ChatResponse)
@limiter.limit("5/minute")
def chat_with_librarian(
    request: Request,
    chat_request: ChatRequest, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    AI 사서와 대화하는 엔드포인트입니다.
    사용자의 메시지를 받아 전체 보유 도서 컨텍스트를 기반으로 답변을 생성합니다.
    - 보안: 1분에 5회 호출 제한 (Rate Limit)
    - 보안: 로그인한 사용자만 접근 가능 (JWT Auth)
    """
    if not chat_request.message or not chat_request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
        
    reply_text = get_ai_response(chat_request.message, db)
    return ChatResponse(reply=reply_text)
