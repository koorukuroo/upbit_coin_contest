"""Redis 캐시 모듈"""
import json
import asyncio
import uuid
import redis.asyncio as redis
from typing import Optional, Any
from functools import wraps
from contextlib import asynccontextmanager
from config import settings


class RedisCache:
    """비동기 Redis 캐시 클래스"""

    _instance: Optional['RedisCache'] = None
    _client: Optional[redis.Redis] = None
    _connected: bool = False

    @classmethod
    async def get_instance(cls) -> 'RedisCache':
        if cls._instance is None:
            cls._instance = cls()
            await cls._instance.connect()
        return cls._instance

    async def connect(self) -> bool:
        """Redis 연결"""
        if self._connected:
            return True

        try:
            self._client = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                password=settings.REDIS_PASSWORD or None,
                db=settings.REDIS_DB,
                ssl=settings.REDIS_SSL,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            # 연결 테스트
            await self._client.ping()
            self._connected = True
            print(f"✅ Redis connected ({settings.REDIS_HOST}:{settings.REDIS_PORT})")
            return True
        except Exception as e:
            print(f"⚠️ Redis connection failed: {e}")
            self._connected = False
            return False

    async def close(self):
        """연결 종료"""
        if self._client:
            await self._client.close()
            self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def get(self, key: str) -> Optional[Any]:
        """캐시 조회"""
        if not self._connected:
            return None
        try:
            data = await self._client.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            print(f"Cache get error: {e}")
            return None

    async def set(self, key: str, value: Any, ttl: int = 60) -> bool:
        """캐시 저장"""
        if not self._connected:
            return False
        try:
            await self._client.setex(key, ttl, json.dumps(value))
            return True
        except Exception as e:
            print(f"Cache set error: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """캐시 삭제"""
        if not self._connected:
            return False
        try:
            await self._client.delete(key)
            return True
        except Exception as e:
            print(f"Cache delete error: {e}")
            return False

    async def delete_pattern(self, pattern: str) -> int:
        """패턴으로 캐시 삭제"""
        if not self._connected:
            return 0
        try:
            keys = []
            async for key in self._client.scan_iter(match=pattern):
                keys.append(key)
            if keys:
                await self._client.delete(*keys)
            return len(keys)
        except Exception as e:
            print(f"Cache delete pattern error: {e}")
            return 0

    async def setnx_with_ttl(self, key: str, value: str, ttl: int) -> bool:
        """키가 없을 때만 설정 (중복 방지용)

        Returns:
            True if key was set (no duplicate), False if key already exists (duplicate)
        """
        if not self._connected:
            return True  # Redis 연결 안되면 통과 (failsafe)
        try:
            # SET key value NX EX ttl - 원자적 연산
            result = await self._client.set(key, value, nx=True, ex=ttl)
            return result is not None
        except Exception as e:
            print(f"Cache setnx error: {e}")
            return True  # 에러 시 통과 (failsafe)

    async def acquire_lock(self, lock_name: str, ttl: int = 10) -> Optional[str]:
        """분산 락 획득

        Args:
            lock_name: 락 이름 (예: "order:user_123")
            ttl: 락 만료 시간 (초), 기본 10초

        Returns:
            lock_token if acquired, None if failed
        """
        if not self._connected:
            return str(uuid.uuid4())  # Redis 연결 안되면 더미 토큰 반환

        lock_token = str(uuid.uuid4())
        try:
            acquired = await self._client.set(
                f"lock:{lock_name}",
                lock_token,
                nx=True,
                ex=ttl
            )
            return lock_token if acquired else None
        except Exception as e:
            print(f"Lock acquire error: {e}")
            return str(uuid.uuid4())  # 에러 시 더미 토큰 반환 (failsafe)

    async def release_lock(self, lock_name: str, lock_token: str) -> bool:
        """분산 락 해제 (토큰 검증으로 안전하게 해제)

        Args:
            lock_name: 락 이름
            lock_token: acquire_lock에서 받은 토큰

        Returns:
            True if released successfully
        """
        if not self._connected:
            return True

        try:
            # Lua 스크립트로 원자적 검증 및 삭제
            script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
            """
            result = await self._client.eval(script, 1, f"lock:{lock_name}", lock_token)
            return result == 1
        except Exception as e:
            print(f"Lock release error: {e}")
            return False

    @asynccontextmanager
    async def distributed_lock(self, lock_name: str, ttl: int = 10, wait_timeout: float = 5.0):
        """분산 락 컨텍스트 매니저

        Usage:
            async with cache.distributed_lock(f"order:{user_id}"):
                await process_order()

        Args:
            lock_name: 락 이름
            ttl: 락 만료 시간 (초)
            wait_timeout: 락 획득 대기 최대 시간 (초)

        Raises:
            TimeoutError: 락 획득 실패 시
        """
        lock_token = None
        start_time = asyncio.get_event_loop().time()

        try:
            # 락 획득 시도 (재시도 포함)
            while True:
                lock_token = await self.acquire_lock(lock_name, ttl)
                if lock_token:
                    break

                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed >= wait_timeout:
                    raise TimeoutError(f"Failed to acquire lock '{lock_name}' within {wait_timeout}s")

                # 50ms 대기 후 재시도
                await asyncio.sleep(0.05)

            yield lock_token

        finally:
            if lock_token:
                await self.release_lock(lock_name, lock_token)


# 전역 캐시 인스턴스
cache: Optional[RedisCache] = None


async def init_cache() -> RedisCache:
    """캐시 초기화"""
    global cache
    cache = await RedisCache.get_instance()
    return cache


async def get_cache() -> Optional[RedisCache]:
    """캐시 인스턴스 반환"""
    global cache
    return cache


def cached(key_prefix: str, ttl: int = 60):
    """캐시 데코레이터"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            global cache

            # 캐시 키 생성
            key_parts = [key_prefix]
            key_parts.extend(str(arg) for arg in args if not hasattr(arg, '__dict__'))
            key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
            cache_key = ":".join(key_parts)

            # 캐시에서 조회
            if cache and cache.is_connected:
                cached_data = await cache.get(cache_key)
                if cached_data is not None:
                    return cached_data

            # 실제 함수 실행
            result = await func(*args, **kwargs)

            # 캐시에 저장
            if cache and cache.is_connected and result is not None:
                await cache.set(cache_key, result, ttl)

            return result
        return wrapper
    return decorator
