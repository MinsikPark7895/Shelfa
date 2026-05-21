import uuid
from sqlalchemy import Column, String, Enum as SQLEnum, DateTime
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
from db.database import Base

class User(Base):
    """
    dbdiagram.io의 'Table 회원'을 파이썬 클래스로 옮긴 ORM 모델입니다.
    이 클래스가 서버 실행 시 자동으로 PostgreSQL에 테이블로 생성됩니다.
    """
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    
    # [회원가입 2번: 암호화] 절대로 plain_password가 아닌 hashed_password가 저장됩니다.
    hashed_password = Column(String, nullable=False)
    
    role = Column(String, default="user") # 'user / admin'
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
