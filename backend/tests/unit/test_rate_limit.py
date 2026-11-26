import pytest
from fakeredis import FakeAsyncRedis
from fastapi import HTTPException
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.config import settings
from app.core.rate_limit import RateLimiter, RateLimitPolicy

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


POLICY = RateLimitPolicy(scope="chat", capacity=3, refill_per_minute=60)


@pytest.fixture
def redis() -> FakeAsyncRedis:
    return FakeAsyncRedis(decode_responses=True)


async def test_allows_burst_then_rejects_with_retry_after(redis):
    limiter = RateLimiter(redis)
    for _ in range(POLICY.capacity):
        await limiter.enforce(POLICY, "user-1")

    with pytest.raises(HTTPException) as error:
        await limiter.enforce(POLICY, "user-1")

    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "1"


async def test_identities_have_separate_buckets(redis):
    limiter = RateLimiter(redis)
    for _ in range(POLICY.capacity):
        await limiter.enforce(POLICY, "user-1")

    await limiter.enforce(POLICY, "user-2")


async def test_scopes_have_separate_buckets(redis):
    limiter = RateLimiter(redis)
    for _ in range(POLICY.capacity):
        await limiter.enforce(POLICY, "user-1")

    await limiter.enforce(RateLimitPolicy("drafts", 3, 60), "user-1")


async def test_tokens_refill_over_time(redis):
    limiter = RateLimiter(redis)
    for _ in range(POLICY.capacity):
        await limiter.enforce(POLICY, "user-1")
    key = "ratelimit:chat:user-1"
    last_refill = int(await redis.hget(key, "ts"))
    await redis.hset(key, "ts", last_refill - 2000)

    await limiter.enforce(POLICY, "user-1")
    await limiter.enforce(POLICY, "user-1")
    with pytest.raises(HTTPException):
        await limiter.enforce(POLICY, "user-1")


async def test_bucket_key_expires(redis):
    await RateLimiter(redis).enforce(POLICY, "user-1")

    assert 0 < await redis.pttl("ratelimit:chat:user-1") <= 4000


async def test_fails_open_when_redis_is_down():
    class DownRedis:
        async def eval(self, *_args):
            raise RedisConnectionError("down")

    await RateLimiter(DownRedis()).enforce(POLICY, "user-1")


async def test_disabled_limiter_skips_redis(monkeypatch):
    class ExplodingRedis:
        async def eval(self, *_args):
            raise AssertionError("redis must not be called")

    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    await RateLimiter(ExplodingRedis()).enforce(POLICY, "user-1")
