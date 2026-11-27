import logging
import math
from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends, HTTPException, status
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.redis import redis_client

logger = logging.getLogger(__name__)

# Atomic token bucket. Time comes from Redis so app replicas cannot disagree.
# Returns {allowed, retry_after_ms}.
TOKEN_BUCKET_SCRIPT = """
local capacity = tonumber(ARGV[1])
local refill_per_ms = tonumber(ARGV[2]) / 60000
local seconds, micros = unpack(redis.call('TIME'))
local now_ms = seconds * 1000 + math.floor(micros / 1000)

local state = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts = tonumber(state[2])
if tokens == nil then
  tokens = capacity
  ts = now_ms
end

tokens = math.min(capacity, tokens + (now_ms - ts) * refill_per_ms)
local allowed = 0
local retry_after_ms = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  retry_after_ms = math.ceil((1 - tokens) / refill_per_ms)
end

redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now_ms)
redis.call('PEXPIRE', KEYS[1], math.ceil(capacity / refill_per_ms) + 1000)
return {allowed, retry_after_ms}
"""


@dataclass(frozen=True)
class RateLimitPolicy:
    scope: str
    capacity: int
    refill_per_minute: int


def chat_policy() -> RateLimitPolicy:
    return RateLimitPolicy(
        "chat", settings.rate_limit_chat_burst, settings.rate_limit_chat_per_minute
    )


def drafts_policy() -> RateLimitPolicy:
    return RateLimitPolicy(
        "drafts", settings.rate_limit_drafts_burst, settings.rate_limit_drafts_per_minute
    )


class ScriptRunner(Protocol):
    async def eval(self, script: str, numkeys: int, *args: str | int) -> list[int]: ...


class RateLimiter:
    def __init__(self, redis: ScriptRunner) -> None:
        self._redis = redis

    async def enforce(self, policy: RateLimitPolicy, identity: str) -> None:
        """Raises 429 with Retry-After when the identity has no tokens left.

        Fails open when Redis is unreachable so a cache outage does not take chat down.
        """
        if not settings.rate_limit_enabled:
            return
        try:
            allowed, retry_after_ms = await self._redis.eval(
                TOKEN_BUCKET_SCRIPT,
                1,
                f"ratelimit:{policy.scope}:{identity}",
                policy.capacity,
                policy.refill_per_minute,
            )
        except RedisError:
            logger.warning("rate limiter unavailable, allowing request", exc_info=True)
            return
        if not allowed:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(max(1, math.ceil(retry_after_ms / 1000)))},
            )


def get_rate_limiter() -> RateLimiter:
    return RateLimiter(redis_client)


RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]
