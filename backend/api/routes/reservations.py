from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from slowapi import Limiter
from slowapi.util import get_remote_address

from db.database import SessionLocal
from db import models, schemas
from api.deps import get_current_user, get_db
from db.schemas import PaginatedResponse
from api.services.mqtt_service import mqtt_service

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

@router.post("/{book_id}", response_model=schemas.ReservationResponse)
@limiter.limit("5/minute")
async def create_reservation(
    request: Request,
    book_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    [예약 API] 선택한 책을 예약합니다. (Race Condition 방어 적용)
    """
    try:
        # Race Condition 방어: with_for_update()를 사용하여 트랜잭션 락(Pessimistic Lock)을 겁니다.
        # 이 트랜잭션이 끝날 때까지 다른 사용자는 이 책의 데이터를 읽거나 수정할 수 없습니다.
        book = db.query(models.Book).filter(models.Book.id == book_id).with_for_update().first()
        
        if not book:
            raise HTTPException(status_code=404, detail="도서를 찾을 수 없습니다.")
            
        if book.status != "AVAILABLE":
            raise HTTPException(status_code=400, detail="현재 예약이 불가능한 상태의 도서입니다.")
            
        # 1. 예약 기록 생성
        new_reservation = models.Reservation(
            user_id=current_user.id,
            book_id=book.id,
            status="PENDING" # 로봇이 가져올 때까지 대기
        )
        
        # 2. 책 상태 업데이트 (다른 사람이 가져가지 못하도록)
        book.status = "RESERVED"
        
        db.add(new_reservation)
        db.commit()
        db.refresh(new_reservation)
        
        # 💡 로봇에게 출동 명령 하달 (MQTT Publish)
        mqtt_service.publish_pickup_command(
            task_id=str(new_reservation.id),
            book_id=str(book.id),
            location=book.shelf_location
        )
        
        return new_reservation
        
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail="예약 처리 중 데이터베이스 오류가 발생했습니다.")

@router.get("/me", response_model=PaginatedResponse[schemas.ReservationResponse])
async def get_my_reservations(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, gt=0, le=50),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """내 예약 목록 조회 (페이지네이션)"""
    base_query = db.query(models.Reservation).filter(models.Reservation.user_id == current_user.id)
    total_count = base_query.count()
    reservations = base_query.order_by(models.Reservation.reserved_at.desc()).offset(skip).limit(limit).all()
    
    return {"total": total_count, "items": reservations}

@router.post("/{reservation_id}/cancel")
async def cancel_reservation(
    reservation_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """예약 취소 로직 (IDOR 방어)"""
    # 1. 예약 기록 조회
    reservation = db.query(models.Reservation).filter(models.Reservation.id == reservation_id).first()
    
    if not reservation:
        raise HTTPException(status_code=404, detail="예약 기록을 찾을 수 없습니다.")
        
    # 2. IDOR / BOLA 방어: 내 예약인지 확인 (남의 예약을 취소할 수 없음)
    if reservation.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="자신의 예약만 취소할 수 있습니다.")
        
    if reservation.status != "PENDING":
         raise HTTPException(status_code=400, detail="이미 처리되었거나 취소된 예약입니다.")
         
    # 3. 책 상태 원상복구 및 예약 취소
    book = db.query(models.Book).filter(models.Book.id == reservation.book_id).first()
    if book:
        book.status = "AVAILABLE"
        
    reservation.status = "CANCELLED"
    db.commit()
    
    return {"message": "예약이 취소되었습니다."}
