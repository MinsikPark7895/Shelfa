from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from contextlib import asynccontextmanager

from db.database import engine, Base, SessionLocal
from db.init_db import init_db_seed
from api.routes import auth, books, loans, reservations, favorites, users
from api.deps import limiter

# [초기 세팅] PostgreSQL에 정의한 모델(테이블)들을 실제 DB에 생성합니다.
Base.metadata.create_all(bind=engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 서버 켜질 때 실행되는 로직: 초기 관리자 계정 생성
    db = SessionLocal()
    try:
        init_db_seed(db)
    finally:
        db.close()
    yield
    # 서버 꺼질 때 실행되는 로직 (필요시 추가)

# FastAPI 앱 인스턴스 생성
app = FastAPI(
    title="Shelfa Backend API (Secure Auth)", 
    description="보안이 강화된 야간 무인 도서 대출 및 로봇 관제 시스템 API",
    version="1.1.0",
    lifespan=lifespan
)

# [가입/로그인 1번: 봇 및 무차별 대입 방어] 앱 전체에 Rate Limiter 적용
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# 라우터(API 엔드포인트) 등록
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(users.router, prefix="/users", tags=["Users"])
app.include_router(books.router, prefix="/books", tags=["Books"])
app.include_router(loans.router, prefix="/loans", tags=["Loans"])
app.include_router(reservations.router, prefix="/reservations", tags=["Reservations"])
app.include_router(favorites.router, prefix="/favorites", tags=["Favorites"])

# 루트 엔드포인트
@app.get("/")
async def read_root():
    return {"message": "Shelfa Backend API is running with Secure Auth!"}

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "shelfa-backend"}
