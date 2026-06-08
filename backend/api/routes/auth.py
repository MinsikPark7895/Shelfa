from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta
import uuid

from api.deps import get_db, limiter
from db import models, schemas, redis_client
from core import security

router = APIRouter()

# [회원가입 3번: 봇 방어 및 열거 공격 방어] 1분에 3회로 가입 시도 제한
@router.post("/signup", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")
def signup(request: Request, user_in: schemas.UserCreate, db: Session = Depends(get_db)):
    # 이메일 중복 체크 (에러 메시지는 모호성 없이 명확히 하되, IP 차단으로 열거 공격을 방어합니다)
    user = db.query(models.User).filter(models.User.email == user_in.email).first()
    if user:
        raise HTTPException(status_code=400, detail="이미 가입된 이메일입니다.")
    
    # [회원가입 2번: 암호화] Pydantic 검사를 통과한 비밀번호를 해싱하여 DB에 저장
    hashed_password = security.get_password_hash(user_in.password)
    
    db_user = models.User(
        name=user_in.name,
        email=user_in.email,
        hashed_password=hashed_password
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

# [로그인 4번: 무차별 대입 방어] 1분에 5회로 로그인 시도 제한
@router.post("/login", response_model=schemas.Token)
@limiter.limit("5/minute")
async def login(request: Request, response: Response, db: Session = Depends(get_db), form_data: OAuth2PasswordRequestForm = Depends()):
    # [로그인 4번: 에러 메시지 모호화] 아이디/비밀번호가 틀려도 동일한 메시지 출력
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not security.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 일치하지 않습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 토큰 생성
    access_token = security.create_access_token(data={"sub": str(user.id)})
    refresh_token = security.create_refresh_token(data={"sub": str(user.id)})
    
    # [로그인 3번: RTR 기반 토큰 탈취 방어] Redis에 Refresh Token 저장
    await redis_client.store_refresh_token(str(user.id), refresh_token)
    
    # [로그인 3번: XSS 및 CSRF 방어] Refresh Token을 HttpOnly, SameSite=Lax 쿠키로 구움
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        max_age=14 * 24 * 60 * 60, # 14일
        samesite="lax", # CSRF 방어
        secure=False, # 로컬 테스트용이므로 False. 실제 배포(HTTPS)시에는 True로 변경해야 함!
    )
    
    # Access Token만 JSON 응답 바디로 전달
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/refresh", response_model=schemas.Token)
async def refresh_token(request: Request, response: Response, db: Session = Depends(get_db)):
    """만료된 Access Token을 쿠키의 Refresh Token을 이용해 재발급합니다."""
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh Token이 없습니다.")
    
    try:
        from jose import jwt
        from core.config import settings
        payload = jwt.decode(refresh_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.")
    except jwt.JWTError:
        raise HTTPException(status_code=401, detail="유효하지 않거나 만료된 Refresh Token입니다.")
    
    # Redis에서 토큰 유효성 검사 (RTR 핵심)
    is_valid = await redis_client.verify_refresh_token(user_id, refresh_token)
    if not is_valid:
        raise HTTPException(status_code=401, detail="폐기되거나 재발급된 Refresh Token입니다. 강제 로그아웃됩니다.")
    
    # [로그인 3번: RTR 기반 토큰 탈취 방어] 검증 완료 시, 기존 토큰을 버리고 두 토큰 모두 새로 발급
    new_access_token = security.create_access_token(data={"sub": user_id})
    new_refresh_token = security.create_refresh_token(data={"sub": user_id})
    
    await redis_client.store_refresh_token(user_id, new_refresh_token)
    
    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        httponly=True,
        max_age=14 * 24 * 60 * 60,
        samesite="lax",
        secure=False,
    )
    
    return {"access_token": new_access_token, "token_type": "bearer"}

@router.post("/logout")
async def logout(request: Request, response: Response):
    """Redis에서 토큰을 지우고 쿠키를 삭제하여 로그아웃 처리합니다."""
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        try:
            from jose import jwt
            from core.config import settings
            payload = jwt.decode(refresh_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            user_id = payload.get("sub")
            if user_id:
                await redis_client.delete_refresh_token(user_id)
        except jwt.JWTError:
            pass # 토큰이 이미 만료되었더라도 쿠키 삭제는 진행
            
    response.delete_cookie("refresh_token")
    return {"message": "로그아웃 되었습니다."}
