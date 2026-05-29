from pydantic import BaseModel, EmailStr, Field, field_validator
import re
import uuid
from datetime import datetime

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    
    # [회원가입 4번: 비밀번호 복잡도 강제 방패막이]
    @field_validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('비밀번호는 최소 8자 이상이어야 합니다.')
        if not re.search(r"[a-zA-Z]", v):
            raise ValueError('비밀번호에 영문자가 포함되어야 합니다.')
        if not re.search(r"\d", v):
            raise ValueError('비밀번호에 숫자가 포함되어야 합니다.')
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError('비밀번호에 특수문자가 포함되어야 합니다.')
        return v

class UserResponse(BaseModel):
    id: uuid.UUID
    name: str
    email: EmailStr
    role: str
    created_at: datetime
    
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str
    # 참고: refresh_token은 응답 바디가 아닌 HttpOnly 쿠키로 전달됩니다.

class BookCreate(BaseModel):
    title: str
    author: str | None = None
    isbn: str
    publisher: str | None = None
    cover_image_url: str | None = None
    shelf_location: str | None = "UNASSIGNED"
    vision_marker_id: str | None = None

class BookResponse(BaseModel):
    id: uuid.UUID
    title: str
    author: str | None = None
    isbn: str
    publisher: str | None = None
    cover_image_url: str | None = None
    shelf_location: str | None = None
    vision_marker_id: str | None = None
    status: str
    created_at: datetime
    
    class Config:
        from_attributes = True

class BulkRegisterRequest(BaseModel):
    """관리자용 대량 입고 요청 스키마"""
    isbns: list[str] = Field(description="입고할 도서들의 ISBN 13자리 목록")
