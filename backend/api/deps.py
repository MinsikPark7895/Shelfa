from typing import Generator
from fastapi import Request
from db.database import SessionLocal
from slowapi import Limiter
from slowapi.util import get_remote_address

# [가입/로그인 1번: 봇 및 무차별 대입 방어] IP 기반 Rate Limiter 설정
limiter = Limiter(key_func=get_remote_address)

def get_db() -> Generator:
    """API 요청마다 독립적인 데이터베이스 세션을 열고 닫습니다."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
