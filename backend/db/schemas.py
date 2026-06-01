from pydantic import BaseModel, EmailStr, Field, field_validator
import re
import uuid
from datetime import datetime

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    
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

class UserUpdate(BaseModel):
    """Mass Assignment 방어: 이름만 수정 가능하도록 제한"""
    name: str | None = None

class PasswordUpdate(BaseModel):
    """계정 탈취 방어: 현재 비밀번호를 필수로 요구"""
    current_password: str
    new_password: str
    
    @field_validator('new_password')
    def validate_new_password(cls, v):
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

class LoanResponse(BaseModel):
    id: uuid.UUID
    book: BookResponse
    borrowed_at: datetime
    due_date: datetime
    status: str
    
    class Config:
        from_attributes = True

class ReservationResponse(BaseModel):
    id: uuid.UUID
    book: BookResponse
    reserved_at: datetime
    status: str
    
    class Config:
        from_attributes = True

class FavoriteResponse(BaseModel):
    id: uuid.UUID
    book: BookResponse
    created_at: datetime
    
    class Config:
        from_attributes = True

from typing import TypeVar, Generic
from pydantic.generics import GenericModel

T = TypeVar('T')
class PaginatedResponse(GenericModel, Generic[T]):
    total: int
    items: list[T]
