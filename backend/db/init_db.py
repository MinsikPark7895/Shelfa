from sqlalchemy.orm import Session
from db import models
from core.config import settings
from core import security

def init_db_seed(db: Session) -> None:
    # 1. DB에 설정된 최고 관리자 이메일이 이미 있는지 확인
    user = db.query(models.User).filter(models.User.email == settings.FIRST_SUPERUSER_EMAIL).first()
    
    # 2. 없다면 새로 생성
    if not user:
        hashed_password = security.get_password_hash(settings.FIRST_SUPERUSER_PASSWORD)
        user = models.User(
            name="최고관리자",
            email=settings.FIRST_SUPERUSER_EMAIL,
            hashed_password=hashed_password,
            role="admin" # 중요: 일반 user가 아닌 admin 권한 부여
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"✅ 최고 관리자 계정이 생성되었습니다: {settings.FIRST_SUPERUSER_EMAIL}")
