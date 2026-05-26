from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from db.database import engine, Base
from api.routes import auth
from api.deps import limiter

# [초기 세팅] PostgreSQL에 정의한 모델(테이블)들을 실제 DB에 생성합니다.
Base.metadata.create_all(bind=engine)

# FastAPI 앱 인스턴스 생성
app = FastAPI(
    title="Shelfa Backend API (Secure Auth)", 
    description="보안이 강화된 야간 무인 도서 대출 및 로봇 관제 시스템 API",
    version="1.1.0"
)

# [가입/로그인 1번: 봇 및 무차별 대입 방어] 앱 전체에 Rate Limiter 적용
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# 라우터(API 엔드포인트) 등록
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])

# 루트 엔드포인트
@app.get("/")
async def read_root():
    return {"message": "Shelfa Backend API is running with Secure Auth!"}

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "shelfa-backend"}
