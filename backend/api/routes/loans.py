from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from datetime import datetime

from db.database import SessionLocal
from db import models, schemas
from api.deps import get_current_user, get_db
from db.schemas import PaginatedResponse

router = APIRouter()

@router.get("/me", response_model=PaginatedResponse[schemas.LoanResponse])
async def get_my_loans(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, gt=0, le=50),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """내 서재 - 대출 현황 조회 API"""
    base_query = db.query(models.Loan).filter(
        models.Loan.user_id == current_user.id,
        models.Loan.status == "ACTIVE" # 현재 빌리고 있는 책만 노출
    )
    total_count = base_query.count()
    loans = base_query.order_by(models.Loan.borrowed_at.desc()).offset(skip).limit(limit).all()
    
    return {"total": total_count, "items": loans}

@router.post("/{loan_id}/return")
async def return_book(
    loan_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    반납 요청 API (IDOR / BOLA 방어 적용)
    """
    loan = db.query(models.Loan).filter(models.Loan.id == loan_id).first()
    
    if not loan:
        raise HTTPException(status_code=404, detail="대출 기록을 찾을 수 없습니다.")
        
    # IDOR / BOLA 보안 검증: 내 대출 기록이 아니면 반납(삭제) 불가
    if loan.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="본인의 책만 반납할 수 있습니다.")
        
    if loan.status == "RETURNED":
        raise HTTPException(status_code=400, detail="이미 반납 처리된 책입니다.")
        
    # TODO: 여기서 로봇 디스펜서 쪽에 "회원이 반납을 시도하니 투입구를 열어라" 명령 전송
    
    # 상태 변경
    loan.status = "RETURNED"
    
    # 도서 상태 업데이트 (이제 다른 사람이 예약 가능)
    book = db.query(models.Book).filter(models.Book.id == loan.book_id).first()
    if book:
        book.status = "AVAILABLE"
        
    db.commit()
    
    return {"message": "정상적으로 반납 처리가 완료되었습니다. 디스펜서에 책을 넣어주세요."}

@router.get("/history", response_model=PaginatedResponse[schemas.LoanResponse])
async def get_loan_history(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, gt=0, le=50),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    마이페이지 - 과거 독서 기록(반납 완료된 대출) 조회 API
    """
    base_query = db.query(models.Loan).filter(
        models.Loan.user_id == current_user.id,
        models.Loan.status == "RETURNED" # 과거에 빌렸던 기록만 노출
    )
    total_count = base_query.count()
    loans = base_query.order_by(models.Loan.borrowed_at.desc()).offset(skip).limit(limit).all()
    
    return {"total": total_count, "items": loans}
