from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address
from db.database import SessionLocal
from db import models, schemas
from api.services.aladin_api import search_book_from_aladin

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

# DB 세션 의존성 주입 함수
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/search_and_save", response_model=schemas.BookResponse)
@limiter.limit("10/minute") # Rate Limiting (1분에 10회로 제한)
async def save_book_from_aladin(request: Request, query: str, db: Session = Depends(get_db)):
    """
    검색어(query)를 받아 알라딘 API에서 책을 찾고, 
    DB에 해당 ISBN의 책이 없다면 새로 저장합니다.
    """
    # 1. 알라딘 API에서 책 정보 가져오기
    book_data = await search_book_from_aladin(query)
    
    if not book_data:
        raise HTTPException(status_code=404, detail="알라딘에서 책을 찾을 수 없습니다.")
        
    # 2. 이미 DB에 있는 책인지 ISBN으로 확인
    existing_book = db.query(models.Book).filter(models.Book.isbn == book_data.get("isbn13")).first()
    if existing_book:
        # 이미 있다면 기존 책 정보 반환 (또는 적절한 메시지와 함께 400에러 반환 가능)
        return existing_book
        
    # 3. 새로운 책 객체 생성 (로봇 위치 데이터는 일단 기본값 설정)
    new_book = models.Book(
        title=book_data.get("title"),
        author=book_data.get("author"),
        isbn=book_data.get("isbn13"),
        publisher=book_data.get("publisher"),
        cover_image_url=book_data.get("cover"),
        shelf_location="UNASSIGNED", # 나중에 관리자가 지정하거나 로봇이 스캔하여 매핑
        vision_marker_id=None,
        status="AVAILABLE"
    )
    
    # 4. DB에 저장
    db.add(new_book)
    db.commit()
    db.refresh(new_book)
    
    return new_book
