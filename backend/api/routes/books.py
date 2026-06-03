from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import APIRouter, Depends, HTTPException, Query
from db.database import SessionLocal
from db import models, schemas
from db.schemas import BulkRegisterRequest, PaginatedResponse
from api.services.aladin_api import search_book_from_aladin, search_book_by_isbn
from api.deps import get_current_admin_user, get_db, get_current_user_optional
from typing import List
import asyncio

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
        description=book_data.get("description"), # 추가: 줄거리 저장
        shelf_location="UNASSIGNED", # 나중에 관리자가 지정하거나 로봇이 스캔하여 매핑
        vision_marker_id=None,
        status="AVAILABLE"
    )
    
    # 4. DB에 저장
    db.add(new_book)
    db.commit()
    db.refresh(new_book)
    
    return new_book

# ==========================================
# 1. 사용자용 API: 로컬 DB 검색 (예약 용도)
# ==========================================
@router.get("/search", response_model=PaginatedResponse[schemas.BookResponse])
@limiter.limit("30/minute")
async def search_local_books(
    request: Request,
    query: str, 
    skip: int = Query(0, ge=0),
    limit: int = Query(20, gt=0, le=100), # Resource Exhaustion 방어: 최대 100개
    db: Session = Depends(get_db)
):
    """
    [사용자용] 우리 도서관(DB)에 이미 입고되어 대출 가능한 책만 검색합니다. (페이지네이션 적용)
    """
    # 쿼리 생성
    base_query = db.query(models.Book).filter(
        models.Book.title.ilike(f"%{query}%"),
        models.Book.status == "AVAILABLE"
    )
    
    # 전체 개수 파악
    total_count = base_query.count()
    
    # 페이지네이션 적용해서 데이터 가져오기
    books = base_query.order_by(models.Book.created_at.desc()).offset(skip).limit(limit).all()
    
    return {"total": total_count, "items": books}

# ==========================================
# 2. 관리자용 API: 대량 도서 신규 입고 (바코드 연동용)
# ==========================================
@router.post("/bulk_register")
async def bulk_register_books(
    request_data: BulkRegisterRequest, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin_user) # 관리자 권한 방어선 추가
):
    """
    [관리자용] 여러 개의 ISBN 바코드 리스트를 받아 한 번에 알라딘에서 정보를 가져오고 DB에 입고시킵니다.
    """
    successful_inserts = 0
    failed_isbns = []
    
    new_books_to_add = []
    
    for isbn in request_data.isbns:
        # 1. 이미 DB에 있는지 확인
        existing_book = db.query(models.Book).filter(models.Book.isbn == isbn).first()
        if existing_book:
            continue # 이미 있는 책은 건너뜀
            
        # 2. 알라딘에서 정확한 ISBN으로 책 조회
        book_data = await search_book_by_isbn(isbn)
        
        if not book_data:
            failed_isbns.append(isbn)
            continue
            
        # 3. 새로운 DB 모델 객체 생성 후 리스트에 담기
        new_book = models.Book(
            title=book_data.get("title"),
            author=book_data.get("author"),
            isbn=book_data.get("isbn13", isbn),
            publisher=book_data.get("publisher"),
            cover_image_url=book_data.get("cover"),
            description=book_data.get("description"), # 추가: 줄거리 저장
            shelf_location="UNASSIGNED", # 입고 대기 상태
            status="IN_STORAGE", # 관리자가 막 등록했으므로 스토리지에 있음
            vision_marker_id=None
        )
        new_books_to_add.append(new_book)
        successful_inserts += 1
        
    # 4. 모아둔 책 객체들을 한 번에 DB에 저장 (성능 최적화)
    if new_books_to_add:
        db.add_all(new_books_to_add)
        db.commit()
        
    return {
        "message": "대량 입고 처리가 완료되었습니다.",
        "success_count": successful_inserts,
        "failed_isbns": failed_isbns
    }

# ==========================================
# 3. 도서 상세 조회 API (찜 여부 포함)
# ==========================================
@router.get("/{book_id}", response_model=schemas.BookDetailResponse)
async def get_book_detail(
    book_id: str,
    db: Session = Depends(get_db),
    current_user: models.User | None = Depends(get_current_user_optional)
):
    """
    [사용자용] 특정 도서의 상세 정보(줄거리 등)와 현재 로그인한 유저의 찜 여부를 반환합니다.
    """
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="도서를 찾을 수 없습니다.")

    is_favorited = False
    if current_user:
        favorite = db.query(models.Favorite).filter(
            models.Favorite.user_id == current_user.id,
            models.Favorite.book_id == book.id
        ).first()
        if favorite:
            is_favorited = True

    # Pydantic 모델 반환을 위해 dict로 변환하거나 객체에 직접 할당
    setattr(book, "is_favorited", is_favorited)
    return book

# ==========================================
# 4. [관리자용] 기존 도서 줄거리 동기화 API
# ==========================================
@router.post("/sync-descriptions")
async def sync_book_descriptions(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin_user)
):
    """
    [관리자용] 줄거리(description)가 없는 기존 도서들의 ISBN을 읽어와서 알라딘 API에서 줄거리를 채워넣습니다.
    (기존 예약 데이터나 ID는 안전하게 보존됩니다.)
    """
    # 줄거리가 비어있는 책들만 검색
    books_to_update = db.query(models.Book).filter(
        (models.Book.description == None) | (models.Book.description == "")
    ).all()
    
    if not books_to_update:
        return {"message": "동기화할 도서가 없습니다. (모든 도서에 줄거리가 존재함)"}

    success_count = 0
    failed_isbns = []

    for book in books_to_update:
        if not book.isbn:
            continue
            
        book_data = await search_book_by_isbn(book.isbn)
        
        if book_data and book_data.get("description"):
            book.description = book_data.get("description")
            success_count += 1
        else:
            failed_isbns.append(book.isbn)
            
        # 알라딘 API Rate Limit 방지를 위해 약간 대기
        await asyncio.sleep(0.1) 

    db.commit()

    return {
        "message": "줄거리 동기화 완료!",
        "total_attempted": len(books_to_update),
        "success_count": success_count,
        "failed_isbns": failed_isbns
    }
