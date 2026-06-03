import uuid
from sqlalchemy import Column, String, Enum as SQLEnum, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
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
    is_active = Column(Boolean, default=True) # Soft Delete (회원 탈퇴 처리용)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Book(Base):
    """
    로봇 워크플로우를 고려한 도서 모델
    """
    __tablename__ = "books"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    title = Column(String, index=True, nullable=False)
    author = Column(String)
    isbn = Column(String, unique=True, index=True)
    publisher = Column(String)
    cover_image_url = Column(String)
    description = Column(String) # 도서 줄거리 (Aladin API 연동)
    
    # 🤖 로봇을 위한 물리적 위치 및 식별 데이터
    shelf_location = Column(String) # 예: "Shelf-A-Row-2"
    vision_marker_id = Column(String) # RealSense 455가 인식할 식별자 (마커 번호나 색상코드)
    status = Column(String, default="AVAILABLE") # AVAILABLE, IN_STORAGE, IN_DISPENSER, RESERVED
    
    created_at = Column(DateTime, default=datetime.utcnow)

    # 역방향 관계 (선택 사항)
    loans = relationship("Loan", back_populates="book")
    reservations = relationship("Reservation", back_populates="book")

class Loan(Base):
    __tablename__ = "loans"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id"), nullable=False)
    borrowed_at = Column(DateTime, default=datetime.utcnow)
    due_date = Column(DateTime, nullable=False)
    status = Column(String, default="ACTIVE") # ACTIVE, RETURNED, OVERDUE
    
    user = relationship("User")
    book = relationship("Book", back_populates="loans")

class Reservation(Base):
    __tablename__ = "reservations"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id"), nullable=False)
    reserved_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="PENDING") # PENDING, APPROVED, CANCELLED, FULFILLED
    
    user = relationship("User")
    book = relationship("Book", back_populates="reservations")

class Favorite(Base):
    __tablename__ = "favorites"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User")
    book = relationship("Book")
