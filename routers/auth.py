"""인증 라우터"""
from typing import Optional
from pydantic import BaseModel

import jwt
import httpx
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from middleware.api_key_auth import get_current_user
from config import settings

router = APIRouter()


def is_admin_email(email: str) -> bool:
    """관리자 이메일인지 확인"""
    admin_emails = [e.strip().lower() for e in settings.ADMIN_EMAILS]
    return email.lower() in admin_emails


async def get_clerk_user_email(clerk_user_id: str) -> Optional[str]:
    """Clerk API를 통해 사용자 이메일 조회"""
    if not settings.CLERK_SECRET_KEY:
        return None

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.clerk.com/v1/users/{clerk_user_id}",
                headers={
                    "Authorization": f"Bearer {settings.CLERK_SECRET_KEY}",
                    "Content-Type": "application/json"
                }
            )
            if response.status_code == 200:
                data = response.json()
                # primary_email_address_id로 이메일 찾기
                email_addresses = data.get("email_addresses", [])
                primary_email_id = data.get("primary_email_address_id")

                for email_obj in email_addresses:
                    if email_obj.get("id") == primary_email_id:
                        return email_obj.get("email_address")

                # primary가 없으면 첫 번째 이메일 반환
                if email_addresses:
                    return email_addresses[0].get("email_address")
    except Exception as e:
        print(f"Error fetching Clerk user email: {e}")

    return None


class UserResponse(BaseModel):
    """사용자 응답"""
    id: str
    email: str
    username: Optional[str]
    is_admin: bool

    class Config:
        from_attributes = True


class UserRegisterRequest(BaseModel):
    """사용자 등록 요청 (선택적 정보)"""
    username: Optional[str] = None


@router.post("/register", response_model=UserResponse)
async def register_user(
    request: Optional[UserRegisterRequest] = None,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """Clerk 인증 후 사용자 등록/로그인

    Clerk JWT 토큰에서 사용자 정보를 추출하여 DB에 등록
    이미 등록된 사용자는 기존 정보 반환
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header required")

    token = authorization.replace("Bearer ", "")

    try:
        # Clerk JWT 디코딩 (서명 검증 생략 - 프로덕션에서는 공개키로 검증 필요)
        payload = jwt.decode(token, options={"verify_signature": False})
        clerk_user_id = payload.get("sub")

    except jwt.DecodeError:
        raise HTTPException(status_code=401, detail="Invalid token")

    if not clerk_user_id:
        raise HTTPException(status_code=401, detail="Invalid token: missing user ID")

    # Clerk API를 통해 실제 이메일 조회
    email = await get_clerk_user_email(clerk_user_id)
    if not email:
        # 폴백: JWT에서 시도
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
            email = payload.get("email") or payload.get("primary_email")
        except:
            pass

    if not email:
        email = f"{clerk_user_id}@clerk.dev"

    # 기존 사용자 확인
    result = await db.execute(
        select(User).where(User.clerk_user_id == clerk_user_id)
    )
    user = result.scalar_one_or_none()

    if user:
        # 기존 사용자의 이메일이 @clerk.dev 폴백인 경우 업데이트
        if user.email.endswith("@clerk.dev") and not email.endswith("@clerk.dev"):
            user.email = email
            user.is_admin = is_admin_email(email)
            await db.commit()
            await db.refresh(user)

        return UserResponse(
            id=str(user.id),
            email=user.email,
            username=user.username,
            is_admin=user.is_admin
        )

    # 새 사용자 생성
    username = request.username if request else None
    user = User(
        clerk_user_id=clerk_user_id,
        email=email,
        username=username,
        is_admin=is_admin_email(email)  # 관리자 이메일이면 자동으로 관리자 권한 부여
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return UserResponse(
        id=str(user.id),
        email=user.email,
        username=user.username,
        is_admin=user.is_admin
    )


@router.get("/me", response_model=UserResponse)
async def get_me(
    user: User = Depends(get_current_user)
):
    """현재 로그인한 사용자 정보 조회"""
    return UserResponse(
        id=str(user.id),
        email=user.email,
        username=user.username,
        is_admin=user.is_admin
    )


@router.put("/me", response_model=UserResponse)
async def update_me(
    request: UserRegisterRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """사용자 정보 업데이트"""
    if request.username:
        user.username = request.username

    await db.commit()
    await db.refresh(user)

    return UserResponse(
        id=str(user.id),
        email=user.email,
        username=user.username,
        is_admin=user.is_admin
    )
