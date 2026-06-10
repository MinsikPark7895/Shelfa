from sqlalchemy.orm import Session
from sqlalchemy import text
from db import models
from core.config import settings
from core import security

def init_db_seed(db: Session) -> None:
    # [자동 스키마 패치] CI/CD 배포 시 운영 서버 DB에 is_active 컬럼이 없어서 서버가 뻗는 현상을 방지합니다.
    try:
        db.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;"))
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"스키마 패치 중 오류 발생 (무시 가능): {e}")

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

    # 3. 책들의 shelf_location 자동 할당 (로봇 주행을 위한 위치 지정)
    # 기존에 책들이 저장되어 있지만 위치값이 없는 경우 ZONE_1, ZONE_2, ZONE_3 중 하나를 부여합니다.
    books = db.query(models.Book).all()
    if books:
        zones = ["ZONE_1", "ZONE_2", "ZONE_3"]
        updated_count = 0
        for i, book in enumerate(books):
            if not book.shelf_location or book.shelf_location not in zones:
                book.shelf_location = zones[i % 3]
                updated_count += 1
                
        if updated_count > 0:
            db.commit()
            print(f"✅ 총 {updated_count}권의 책에 로봇 픽업 위치(ZONE_1~3)가 성공적으로 할당되었습니다.")
