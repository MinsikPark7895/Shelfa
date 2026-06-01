from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from db.database import SessionLocal
from db import models, schemas
from api.deps import get_current_user, get_db
from db.schemas import PaginatedResponse

router = APIRouter()

@router.get("/me", response_model=PaginatedResponse[schemas.FavoriteResponse])
async def get_my_favorites(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, gt=0, le=100),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """내 서재 - 관심 도서 목록 조회 API"""
    base_query = db.query(models.Favorite).filter(models.Favorite.user_id == current_user.id)
    total_count = base_query.count()
    favorites = base_query.order_by(models.Favorite.created_at.desc()).offset(skip).limit(limit).all()
    
    return {"total": total_count, "items": favorites}

@router.post("/{book_id}")
async def add_favorite(
    book_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """관심 도서 찜하기"""
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="도서를 찾을 수 없습니다.")
        
    # 중복 찜 방지
    existing_favorite = db.query(models.Favorite).filter(
        models.Favorite.user_id == current_user.id,
        models.Favorite.book_id == book_id
    ).first()
    
    if existing_favorite:
         raise HTTPException(status_code=400, detail="이미 관심 도서로 등록되어 있습니다.")
         
    new_favorite = models.Favorite(user_id=current_user.id, book_id=book.id)
    db.add(new_favorite)
    db.commit()
    
    return {"message": "관심 도서로 등록되었습니다."}

@router.delete("/{book_id}")
async def remove_favorite(
    book_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """관심 도서 찜 취소하기 (IDOR 완벽 방어)"""
    # 쿼리 자체에서 current_user.id를 조건으로 걸기 때문에 타인의 데이터를 지울 확률 0%
    favorite = db.query(models.Favorite).filter(
        models.Favorite.user_id == current_user.id,
        models.Favorite.book_id == book_id
    ).first()
    
    if not favorite:
        raise HTTPException(status_code=404, detail="관심 도서 목록에 해당 책이 없습니다.")
        
    db.delete(favorite)
    db.commit()
    
    return {"message": "관심 도서 목록에서 삭제되었습니다."}
