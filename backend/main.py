from fastapi import FastAPI

# FastAPI 앱 인스턴스 생성
app = FastAPI(
    title="Shelfa Backend API", # API 문서 제목
    description="야간 무인 도서 대출 및 로봇 관제 시스템 API",
    version="1.0.0"
)


# 루트 엔드포인트
@app.get("/")
async def read_root():
    return {"message": "Shelfa Backend API is running!"}

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "shelfa-backend"}
