"""API Key 및 Clerk JWT 인증 미들웨어"""
import hashlib
from datetime import datetime
from typing import Optional
from functools import lru_cache

import jwt
from jwt import PyJWKClient
import httpx
from fastapi import Depends, HTTPException, Header
from fastapi.security import APIKeyHeader
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from models.api_key import ApiKey
from config import settings


# Clerk JWKS URL (Clerk의 공개 키를 가져오기 위함)
# CLERK_PUBLISHABLE_KEY에서 도메인 추출 (pk_live_ 또는 pk_test_ 이후 base64 디코딩)
@lru_cache(maxsize=1)
def get_jwks_client() -> Optional[PyJWKClient]:
    """Clerk JWKS 클라이언트 생성 (캐싱됨)"""
    if not settings.CLERK_PUBLISHABLE_KEY:
        return None
    try:
        import base64
        # pk_live_xxxx 또는 pk_test_xxxx 형식에서 도메인 추출
        key_part = settings.CLERK_PUBLISHABLE_KEY.split("_")[-1]
        # base64 디코딩하여 도메인 얻기
        domain = base64.b64decode(key_part + "==").decode("utf-8").rstrip("$")
        jwks_url = f"https://{domain}/.well-known/jwks.json"
        return PyJWKClient(jwks_url)
    except Exception:
        return None


# API Key 헤더
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    api_key: Optional[str] = Depends(api_key_header),
    db: AsyncSession = Depends(get_db)
) -> ApiKey:
    """API Key 인증

    Returns:
        ApiKey: 유효한 API Key 레코드
    """
    if not api_key:
        raise HTTPException(status_code=401, detail="API Key required")

    # SHA256 해시로 변환
    hashed_key = hashlib.sha256(api_key.encode()).hexdigest()

    # DB에서 조회
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.api_key == hashed_key,
            ApiKey.is_active == True
        )
    )
    api_key_record = result.scalar_one_or_none()

    if not api_key_record:
        raise HTTPException(status_code=401, detail="Invalid API Key")

    # 마지막 사용 시간 업데이트
    await db.execute(
        update(ApiKey)
        .where(ApiKey.id == api_key_record.id)
        .values(last_used_at=datetime.utcnow())
    )
    await db.commit()

    return api_key_record


async def get_user_from_api_key(
    api_key_record: ApiKey = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db)
) -> User:
    """API Key로부터 사용자 조회"""
    result = await db.execute(
        select(User).where(User.id == api_key_record.user_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user


async def get_current_user(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Clerk JWT 토큰으로 현재 사용자 조회

    Authorization 헤더: Bearer <token>
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header required")

    token = authorization.replace("Bearer ", "")

    try:
        # Clerk JWKS를 사용하여 JWT 서명 검증
        jwks_client = get_jwks_client()

        if jwks_client:
            # JWKS를 사용하여 서명 검증
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                options={"verify_aud": False}  # Clerk는 audience를 사용하지 않음
            )
        else:
            # JWKS를 사용할 수 없는 경우 (개발 환경 등)
            # 경고: 프로덕션에서는 반드시 CLERK_PUBLISHABLE_KEY를 설정하세요
            payload = jwt.decode(token, options={"verify_signature": False})

        clerk_user_id = payload.get("sub")

        if not clerk_user_id:
            raise HTTPException(status_code=401, detail="Invalid token")

        # 사용자 조회
        result = await db.execute(
            select(User).where(User.clerk_user_id == clerk_user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        return user

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.DecodeError:
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception:
        raise HTTPException(status_code=401, detail="Token verification failed")


async def verify_admin(
    user: User = Depends(get_current_user)
) -> User:
    """관리자 권한 확인"""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def generate_api_key() -> dict:
    """새 API Key 생성

    Returns:
        dict: {
            "raw_key": 원본 키 (사용자에게 1회만 표시),
            "prefix": 표시용 prefix,
            "hashed_key": DB 저장용 해시
        }
    """
    import secrets

    raw_key = secrets.token_hex(32)  # 64자 hex string
    prefix = raw_key[:8]
    hashed_key = hashlib.sha256(raw_key.encode()).hexdigest()

    return {
        "raw_key": raw_key,
        "prefix": prefix,
        "hashed_key": hashed_key
    }
