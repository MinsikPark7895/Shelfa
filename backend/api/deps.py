from typing import Generator
from fastapi import Request, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.orm import Session
from db.database import SessionLocal
from db import models
from core.config import settings
from slowapi import Limiter
from slowapi.util import get_remote_address

# [가입/로그인 1번: 봇 및 무차별 대입 방어] IP 기반 Rate Limiter 설정
limiter = Limiter(key_func=get_remote_address)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

def get_db() -> Generator:
    """API 요청마다 독립적인 데이터베이스 세션을 열고 닫습니다."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def get_current_user(db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)) -> models.User:
    """토큰을 검증하여 현재 로그인한 사용자 객체를 반환합니다."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="자격 증명(토큰)이 유효하지 않습니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user is None:
        raise credentials_exception
        
    # [Soft Delete 방어] 탈퇴한 사용자 접근 차단
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="비활성화되거나 탈퇴한 계정입니다."
        )
        
    return user

async def get_current_admin_user(current_user: models.User = Depends(get_current_user)) -> models.User:
    """로그인한 사용자가 '관리자(admin)' 권한을 가졌는지 검사합니다."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="이 작업을 수행할 권한(관리자)이 없습니다."
        )
    return current_user
