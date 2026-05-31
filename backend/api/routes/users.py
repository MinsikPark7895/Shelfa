from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime

from db.database import SessionLocal
from db import models, schemas, redis_client
from api.deps import get_current_user, get_db
from core import security

router = APIRouter()

@router.get("/me", response_model=schemas.UserResponse)
async def get_my_profile(current_user: models.User = Depends(get_current_user)):
    """내 프로필 조회 (IDOR 방어)"""
    return current_user

@router.get("/me/summary")
async def get_my_summary(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """마이페이지 대시보드 통계 요약 (IDOR 방어)"""
    total_borrowed = db.query(models.Loan).filter(
        models.Loan.user_id == current_user.id,
        models.Loan.status == "RETURNED"
    ).count()
    
    currently_borrowing = db.query(models.Loan).filter(
        models.Loan.user_id == current_user.id,
        models.Loan.status == "ACTIVE"
    ).count()
    
    current_reservations = db.query(models.Reservation).filter(
        models.Reservation.user_id == current_user.id,
        models.Reservation.status == "PENDING"
    ).count()
    
    return {
        "total_books_read": total_borrowed,
        "active_loans": currently_borrowing,
        "active_reservations": current_reservations
    }

@router.put("/me", response_model=schemas.UserResponse)
async def update_my_profile(
    user_data: schemas.UserUpdate, # Mass Assignment 방어 (role 조작 불가)
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """내 기본 정보(이름) 수정"""
    if user_data.name:
        current_user.name = user_data.name
        
    db.commit()
    db.refresh(current_user)
    return current_user

@router.put("/me/password")
async def update_my_password(
    passwords: schemas.PasswordUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """비밀번호 변경 (계정 탈취 방어 및 강제 로그아웃)"""
    # 1. 현재 비밀번호 확인
    if not security.verify_password(passwords.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="현재 비밀번호가 일치하지 않습니다.")
        
    # 2. 새 비밀번호 해싱 및 저장
    current_user.hashed_password = security.get_password_hash(passwords.new_password)
    db.commit()
    
    # 3. Redis에서 현재 유저의 토큰을 모두 날려서, PC방 등에서 켜진 다른 세션들을 전부 로그아웃 처리
    await redis_client.delete_refresh_token(str(current_user.id))
    
    return {"message": "비밀번호가 성공적으로 변경되었습니다. 보안을 위해 모든 기기에서 로그아웃 되었습니다."}

@router.delete("/me")
async def withdraw_account(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """회원 탈퇴 (Soft Delete / Cascade Data Loss 방어)"""
    
    # 대출 중인 책이 있는지 검사
    active_loans = db.query(models.Loan).filter(
        models.Loan.user_id == current_user.id,
        models.Loan.status == "ACTIVE"
    ).count()
    if active_loans > 0:
        raise HTTPException(status_code=400, detail="대출 중인 도서가 있어 탈퇴할 수 없습니다. 모두 반납 후 시도해 주세요.")
    
    # 예약 중인 내역 전부 취소 처리
    db.query(models.Reservation).filter(
        models.Reservation.user_id == current_user.id,
        models.Reservation.status == "PENDING"
    ).update({"status": "CANCELLED"}, synchronize_session=False)
    
    # 찜 목록(Favorites)은 굳이 남길 필요가 없으므로 물리 삭제
    db.query(models.Favorite).filter(models.Favorite.user_id == current_user.id).delete(synchronize_session=False)
    
    # 회원 정보 Soft Delete 및 익명화
    current_user.is_active = False
    current_user.name = "탈퇴한 사용자"
    current_user.email = f"deleted_{current_user.id}@shelfa.co.kr" # 이메일 재가입 방지 및 익명화
    current_user.hashed_password = ""
    
    db.commit()
    
    # 세션 강제 종료
    await redis_client.delete_refresh_token(str(current_user.id))
    
    return {"message": "회원 탈퇴가 안전하게 완료되었습니다. 이용해 주셔서 감사합니다."}
