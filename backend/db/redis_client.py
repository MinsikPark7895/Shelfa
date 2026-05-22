import redis.asyncio as redis
from core.config import settings

# [로그인 3번: 토큰 관리 및 RTR] 비동기 Redis 클라이언트 생성
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

async def store_refresh_token(user_id: str, refresh_token: str):
    """Redis에 Refresh Token을 저장합니다. 만료기간은 설정값(14일)과 동일하게 잡습니다."""
    expire_seconds = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    await redis_client.setex(name=f"refresh:{user_id}", time=expire_seconds, value=refresh_token)

async def verify_refresh_token(user_id: str, refresh_token: str) -> bool:
    """Redis에 저장된 Refresh Token이 유효한지 확인합니다."""
    stored_token = await redis_client.get(f"refresh:{user_id}")
    return stored_token == refresh_token

async def delete_refresh_token(user_id: str):
    """로그아웃 시 Redis에서 Refresh Token을 폐기합니다."""
    await redis_client.delete(f"refresh:{user_id}")
