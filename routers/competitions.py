"""대회 라우터"""
import json
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from models.api_key import ApiKey
from models.competition import Competition
from models.participant import Participant
from models.position import Position
from models.order import Order
from models.trade import Trade
from middleware.api_key_auth import verify_api_key, get_user_from_api_key
from config import settings
from cache import get_cache

router = APIRouter()


class CompetitionResponse(BaseModel):
    """대회 응답"""
    id: str
    name: str
    description: Optional[str]
    initial_balance: float
    fee_rate: float
    start_time: datetime
    end_time: datetime
    status: str
    participant_count: int

    class Config:
        from_attributes = True


class ParticipantResponse(BaseModel):
    """참가자 응답"""
    id: str
    balance: float
    joined_at: datetime


class LeaderboardEntry(BaseModel):
    """리더보드 항목"""
    rank: int
    username: Optional[str]
    total_asset: float
    balance: float
    coin_value: float
    profit_rate: float
    trade_count: int = 0


@router.get("", response_model=List[CompetitionResponse])
async def list_competitions(
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """대회 목록 조회"""
    query = select(Competition)
    if status:
        query = query.where(Competition.status == status)
    query = query.order_by(Competition.start_time.desc())

    result = await db.execute(query)
    competitions = result.scalars().all()

    response = []
    for comp in competitions:
        # 참가자 수 조회
        count_result = await db.execute(
            select(func.count()).select_from(Participant).where(
                Participant.competition_id == comp.id
            )
        )
        participant_count = count_result.scalar() or 0

        response.append(CompetitionResponse(
            id=str(comp.id),
            name=comp.name,
            description=comp.description,
            initial_balance=float(comp.initial_balance),
            fee_rate=float(comp.fee_rate),
            start_time=comp.start_time,
            end_time=comp.end_time,
            status=comp.status,
            participant_count=participant_count
        ))

    return response


@router.get("/active", response_model=Optional[CompetitionResponse])
async def get_active_competition(
    db: AsyncSession = Depends(get_db)
):
    """현재 진행 중인 대회 조회"""
    result = await db.execute(
        select(Competition)
        .where(Competition.status == "active")
        .order_by(Competition.start_time.desc())
        .limit(1)
    )
    comp = result.scalar_one_or_none()

    if not comp:
        return None

    # 참가자 수 조회
    count_result = await db.execute(
        select(func.count()).select_from(Participant).where(
            Participant.competition_id == comp.id
        )
    )
    participant_count = count_result.scalar() or 0

    return CompetitionResponse(
        id=str(comp.id),
        name=comp.name,
        description=comp.description,
        initial_balance=float(comp.initial_balance),
        fee_rate=float(comp.fee_rate),
        start_time=comp.start_time,
        end_time=comp.end_time,
        status=comp.status,
        participant_count=participant_count
    )


@router.get("/{competition_id}", response_model=CompetitionResponse)
async def get_competition(
    competition_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """대회 상세 조회"""
    result = await db.execute(
        select(Competition).where(Competition.id == competition_id)
    )
    comp = result.scalar_one_or_none()

    if not comp:
        raise HTTPException(status_code=404, detail="Competition not found")

    # 참가자 수 조회
    count_result = await db.execute(
        select(func.count()).select_from(Participant).where(
            Participant.competition_id == comp.id
        )
    )
    participant_count = count_result.scalar() or 0

    return CompetitionResponse(
        id=str(comp.id),
        name=comp.name,
        description=comp.description,
        initial_balance=float(comp.initial_balance),
        fee_rate=float(comp.fee_rate),
        start_time=comp.start_time,
        end_time=comp.end_time,
        status=comp.status,
        participant_count=participant_count
    )


@router.post("/{competition_id}/join", response_model=ParticipantResponse)
async def join_competition(
    competition_id: UUID,
    api_key: ApiKey = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db)
):
    """대회 참가"""
    # 대회 조회
    result = await db.execute(
        select(Competition).where(Competition.id == competition_id)
    )
    comp = result.scalar_one_or_none()

    if not comp:
        raise HTTPException(status_code=404, detail="Competition not found")

    if comp.status != "active":
        raise HTTPException(status_code=400, detail="Competition is not active")

    # 이미 이 대회에 참가 중인지 확인
    result = await db.execute(
        select(Participant).where(
            Participant.competition_id == competition_id,
            Participant.user_id == api_key.user_id
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        raise HTTPException(status_code=400, detail="Already participating")

    # 다른 활성 대회에 참가 중인지 확인
    result = await db.execute(
        select(Participant, Competition)
        .join(Competition, Participant.competition_id == Competition.id)
        .where(
            Participant.user_id == api_key.user_id,
            Competition.status == "active",
            Competition.id != competition_id
        )
    )
    active_participation = result.first()

    if active_participation:
        other_comp = active_participation[1]
        raise HTTPException(
            status_code=400,
            detail=f"이미 다른 대회에 참가 중입니다: {other_comp.name}"
        )

    # 참가자 등록
    participant = Participant(
        competition_id=competition_id,
        user_id=api_key.user_id,
        balance=comp.initial_balance
    )
    db.add(participant)
    await db.commit()
    await db.refresh(participant)

    return ParticipantResponse(
        id=str(participant.id),
        balance=float(participant.balance),
        joined_at=participant.joined_at
    )


@router.get("/{competition_id}/leaderboard", response_model=List[LeaderboardEntry])
async def get_leaderboard(
    competition_id: UUID,
    current_prices: Optional[str] = None,  # JSON string of {code: price}
    db: AsyncSession = Depends(get_db)
):
    """리더보드 조회

    current_prices: 현재 시세 (없으면 잔고만으로 계산)
    예: {"KRW-BTC": 150000000, "KRW-ETH": 5000000}
    """
    # 캐시 키 생성 (시세 없는 기본 리더보드만 캐시)
    cache_key = f"leaderboard:{competition_id}"

    # 시세 없이 조회하는 경우에만 캐시 사용
    cache = await get_cache()
    if not current_prices and cache and cache.is_connected:
        cached = await cache.get(cache_key)
        if cached:
            return [LeaderboardEntry(**entry) for entry in cached]

    # 대회 조회
    result = await db.execute(
        select(Competition).where(Competition.id == competition_id)
    )
    comp = result.scalar_one_or_none()

    if not comp:
        raise HTTPException(status_code=404, detail="Competition not found")

    # 현재 시세 파싱
    prices = {}
    if current_prices:
        try:
            prices = json.loads(current_prices)
        except json.JSONDecodeError:
            pass

    # 참가자 조회
    result = await db.execute(
        select(Participant, User)
        .join(User, Participant.user_id == User.id)
        .where(Participant.competition_id == competition_id)
    )
    participants = result.all()

    leaderboard = []
    initial_balance = float(comp.initial_balance)

    for participant, user in participants:
        # 포지션 조회
        pos_result = await db.execute(
            select(Position).where(Position.participant_id == participant.id)
        )
        positions = pos_result.scalars().all()

        # 코인 평가액 계산
        coin_value = 0.0
        for pos in positions:
            price = prices.get(pos.code, 0)
            coin_value += float(pos.quantity) * price

        # pending 주문에 묶인 자산 계산
        pending_result = await db.execute(
            select(Order).where(
                Order.participant_id == participant.id,
                Order.status == "pending"
            )
        )
        pending_orders = pending_result.scalars().all()

        pending_amount = 0.0
        fee_rate = float(settings.FEE_RATE)
        for order in pending_orders:
            if order.side == "buy":
                # 매수 대기: 지정가 * 수량 + 수수료 (KRW로 묶여있음)
                order_amount = float(order.price) * float(order.quantity)
                order_fee = order_amount * fee_rate
                pending_amount += order_amount + order_fee
            else:
                # 매도 대기: 현재 시세로 코인 가치 계산 (포지션에서 차감되어 있음)
                current_price = prices.get(order.code, 0)
                pending_amount += float(order.quantity) * current_price

        # 거래 횟수 조회
        trade_count_result = await db.execute(
            select(func.count()).select_from(Trade).where(
                Trade.participant_id == participant.id
            )
        )
        trade_count = trade_count_result.scalar() or 0

        balance = float(participant.balance)
        total_asset = balance + coin_value + pending_amount
        profit_rate = (total_asset - initial_balance) / initial_balance * 100

        leaderboard.append({
            "username": user.username or user.email.split("@")[0],
            "total_asset": total_asset,
            "balance": balance,
            "coin_value": coin_value,
            "profit_rate": profit_rate,
            "trade_count": trade_count
        })

    # 현금(balance) 내림차순 정렬
    leaderboard.sort(key=lambda x: x["balance"], reverse=True)

    # 순위 부여
    result_data = [
        {"rank": i + 1, **entry}
        for i, entry in enumerate(leaderboard)
    ]

    # 시세 없이 조회하는 경우에만 캐시 저장 (10초 TTL)
    if not current_prices and cache and cache.is_connected:
        await cache.set(cache_key, result_data, settings.CACHE_TTL_LEADERBOARD)

    return [LeaderboardEntry(**entry) for entry in result_data]


@router.get("/{competition_id}/my-status", response_model=Optional[ParticipantResponse])
async def get_my_status(
    competition_id: UUID,
    api_key: ApiKey = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db)
):
    """내 참가 상태 조회"""
    result = await db.execute(
        select(Participant).where(
            Participant.competition_id == competition_id,
            Participant.user_id == api_key.user_id
        )
    )
    participant = result.scalar_one_or_none()

    if not participant:
        return None

    return ParticipantResponse(
        id=str(participant.id),
        balance=float(participant.balance),
        joined_at=participant.joined_at
    )
