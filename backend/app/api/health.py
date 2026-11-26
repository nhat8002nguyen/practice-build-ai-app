from fastapi import APIRouter
from redis.exceptions import RedisError

from app.core.redis import ping_redis


router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    try:
        redis_status = "ok" if await ping_redis() else "unavailable"
    except RedisError:
        redis_status = "unavailable"

    return {"status": "ok", "redis": redis_status}
