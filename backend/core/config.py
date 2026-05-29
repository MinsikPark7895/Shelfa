import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Shelfa Backend API"
    
    # [로그인 2번: 암호화/JWT] 서버가 토큰을 발급할 때 사용하는 비밀 키 (실제 배포시에는 환경변수로 숨겨야 합니다)
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    
    # JWT 만료 시간 설정
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30 # 30분
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14 # 14일
    
    # PostgreSQL 데이터베이스 주소
    DATABASE_URL: str
    
    # Redis 접속 주소
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # 알라딘 Open API 인증키
    ALADIN_TTB_KEY: str
    
    # 최고 관리자 설정
    FIRST_SUPERUSER_EMAIL: str
    FIRST_SUPERUSER_PASSWORD: str
    
    # .env 파일에서 환경변수를 자동으로 불러옵니다.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
