"""API Key 관리 라우터"""
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from models.api_key import ApiKey
from middleware.api_key_auth import get_current_user, generate_api_key

router = APIRouter()


class ApiKeyCreate(BaseModel):
    """API Key 생성 요청"""
    name: Optional[str] = "Default"


class ApiKeyResponse(BaseModel):
    """API Key 응답 (생성 시에만 raw_key 포함)"""
    id: str
    name: str
    prefix: str
    api_key: Optional[str] = None  # 생성 시에만 포함
    is_active: bool
    last_used_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


@router.post("", response_model=ApiKeyResponse)
async def create_api_key(
    request: ApiKeyCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """새 API Key 발급

    주의: api_key는 이 응답에서만 확인 가능합니다. 안전하게 보관하세요.
    """
    # 기존 API Key 개수 확인 (최대 5개)
    result = await db.execute(
        select(ApiKey).where(ApiKey.user_id == user.id, ApiKey.is_active == True)
    )
    existing_keys = result.scalars().all()

    if len(existing_keys) >= 5:
        raise HTTPException(status_code=400, detail="Maximum 5 active API keys allowed")

    # 새 키 생성
    key_data = generate_api_key()

    api_key = ApiKey(
        user_id=user.id,
        api_key=key_data["hashed_key"],
        api_key_prefix=key_data["prefix"],
        name=request.name or "Default"
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    return ApiKeyResponse(
        id=str(api_key.id),
        name=api_key.name,
        prefix=api_key.api_key_prefix,
        api_key=key_data["raw_key"],  # 원본 키는 여기서만 반환
        is_active=api_key.is_active,
        last_used_at=api_key.last_used_at,
        created_at=api_key.created_at
    )


@router.get("", response_model=List[ApiKeyResponse])
async def list_api_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """내 API Key 목록 조회"""
    result = await db.execute(
        select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())
    )
    keys = result.scalars().all()

    return [
        ApiKeyResponse(
            id=str(key.id),
            name=key.name,
            prefix=key.api_key_prefix,
            api_key=None,  # 목록에서는 원본 키 미포함
            is_active=key.is_active,
            last_used_at=key.last_used_at,
            created_at=key.created_at
        )
        for key in keys
    ]


@router.delete("/{key_id}")
async def delete_api_key(
    key_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """API Key 삭제"""
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id)
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(status_code=404, detail="API Key not found")

    await db.execute(
        delete(ApiKey).where(ApiKey.id == key_id)
    )
    await db.commit()

    return {"message": "API Key deleted"}


@router.post("/{key_id}/deactivate")
async def deactivate_api_key(
    key_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """API Key 비활성화"""
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id)
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(status_code=404, detail="API Key not found")

    api_key.is_active = False
    await db.commit()

    return {"message": "API Key deactivated"}


@router.post("/{key_id}/activate")
async def activate_api_key(
    key_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """API Key 활성화"""
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id)
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(status_code=404, detail="API Key not found")

    api_key.is_active = True
    await db.commit()

    return {"message": "API Key activated"}
