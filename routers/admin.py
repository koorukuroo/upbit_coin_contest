"""관리자 라우터"""
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from models.competition import Competition
from models.participant import Participant
from models.position import Position
from models.order import Order
from models.trade import Trade
from middleware.api_key_auth import get_current_user
from config import settings
from services.order_service import PRICE_RANGES, validate_price

router = APIRouter()


class CompetitionCreate(BaseModel):
    """대회 생성 요청"""
    name: str
    description: Optional[str] = None
    initial_balance: float = 1000000
    fee_rate: float = 0.0005
    start_time: datetime
    end_time: datetime


class CompetitionUpdate(BaseModel):
    """대회 수정 요청"""
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None


class CompetitionAdminResponse(BaseModel):
    """대회 관리자 응답"""
    id: str
    name: str
    description: Optional[str]
    initial_balance: float
    fee_rate: float
    start_time: datetime
    end_time: datetime
    status: str
    created_at: datetime
    participant_count: int = 0

    class Config:
        from_attributes = True


class ParticipantAdminResponse(BaseModel):
    """참가자 관리자 응답 (실명 포함)"""
    id: str
    user_id: str
    email: str
    username: Optional[str]
    balance: float
    coin_value: float
    total_asset: float
    profit_rate: float
    joined_at: datetime
    order_count: int
    trade_count: int

    class Config:
        from_attributes = True


class AwardRequest(BaseModel):
    """상금 지급 요청"""
    participant_id: str
    amount: float
    reason: str = "상금 지급"


class CompetitionUpdateFull(BaseModel):
    """대회 전체 수정 요청"""
    name: Optional[str] = None
    description: Optional[str] = None
    initial_balance: Optional[float] = None
    fee_rate: Optional[float] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    status: Optional[str] = None


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """관리자 권한 확인 (이메일 기반)"""
    # 허용된 관리자 이메일 목록에 있는지 확인
    admin_emails = [email.strip().lower() for email in settings.ADMIN_EMAILS]
    if user.email.lower() not in admin_emails:
        raise HTTPException(
            status_code=403,
            detail=f"Admin access required. Your email: {user.email}"
        )
    return user


def to_naive_utc(dt: datetime) -> datetime:
    """timezone-aware datetime을 naive UTC로 변환"""
    if dt.tzinfo is not None:
        # UTC로 변환 후 timezone 제거
        from datetime import timezone
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


@router.post("/competitions", response_model=CompetitionAdminResponse)
async def create_competition(
    request: CompetitionCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """대회 생성 (관리자 전용)"""
    # 시간 검증
    if request.start_time >= request.end_time:
        raise HTTPException(status_code=400, detail="end_time must be after start_time")

    # timezone-aware datetime을 naive UTC로 변환
    start_time = to_naive_utc(request.start_time)
    end_time = to_naive_utc(request.end_time)

    # 대회 생성
    competition = Competition(
        name=request.name,
        description=request.description,
        initial_balance=Decimal(str(request.initial_balance)),
        fee_rate=Decimal(str(request.fee_rate)),
        start_time=start_time,
        end_time=end_time,
        status="pending"
    )
    db.add(competition)
    await db.commit()
    await db.refresh(competition)

    return CompetitionAdminResponse(
        id=str(competition.id),
        name=competition.name,
        description=competition.description,
        initial_balance=float(competition.initial_balance),
        fee_rate=float(competition.fee_rate),
        start_time=competition.start_time,
        end_time=competition.end_time,
        status=competition.status,
        created_at=competition.created_at
    )


@router.put("/competitions/{competition_id}", response_model=CompetitionAdminResponse)
async def update_competition(
    competition_id: UUID,
    request: CompetitionUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """대회 수정 (관리자 전용)"""
    result = await db.execute(
        select(Competition).where(Competition.id == competition_id)
    )
    competition = result.scalar_one_or_none()

    if not competition:
        raise HTTPException(status_code=404, detail="Competition not found")

    # 상태 변경 검증
    if request.status:
        valid_statuses = ["pending", "active", "ended"]
        if request.status not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Must be one of: {valid_statuses}"
            )

    # 필드 업데이트
    if request.name:
        competition.name = request.name
    if request.description is not None:
        competition.description = request.description
    if request.status:
        competition.status = request.status

    await db.commit()
    await db.refresh(competition)

    return CompetitionAdminResponse(
        id=str(competition.id),
        name=competition.name,
        description=competition.description,
        initial_balance=float(competition.initial_balance),
        fee_rate=float(competition.fee_rate),
        start_time=competition.start_time,
        end_time=competition.end_time,
        status=competition.status,
        created_at=competition.created_at
    )


@router.post("/competitions/{competition_id}/activate")
async def activate_competition(
    competition_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """대회 활성화 (관리자 전용)"""
    result = await db.execute(
        select(Competition).where(Competition.id == competition_id)
    )
    competition = result.scalar_one_or_none()

    if not competition:
        raise HTTPException(status_code=404, detail="Competition not found")

    if competition.status == "ended":
        raise HTTPException(status_code=400, detail="Cannot activate ended competition")

    # 여러 대회가 동시에 active 가능 (단, 한 계정은 하나의 대회에만 참가 가능)
    competition.status = "active"
    await db.commit()

    return {"message": f"Competition '{competition.name}' activated"}


@router.post("/competitions/{competition_id}/end")
async def end_competition(
    competition_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """대회 종료 (관리자 전용)"""
    result = await db.execute(
        select(Competition).where(Competition.id == competition_id)
    )
    competition = result.scalar_one_or_none()

    if not competition:
        raise HTTPException(status_code=404, detail="Competition not found")

    competition.status = "ended"
    await db.commit()

    return {"message": f"Competition '{competition.name}' ended"}


@router.delete("/competitions/{competition_id}")
async def delete_competition(
    competition_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """대회 삭제 (관리자 전용, 참가자 없는 경우만)"""
    result = await db.execute(
        select(Competition).where(Competition.id == competition_id)
    )
    competition = result.scalar_one_or_none()

    if not competition:
        raise HTTPException(status_code=404, detail="Competition not found")

    # 참가자 확인
    result = await db.execute(
        select(Participant).where(Participant.competition_id == competition_id).limit(1)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail="Cannot delete competition with participants"
        )

    await db.delete(competition)
    await db.commit()

    return {"message": "Competition deleted"}


@router.get("/competitions", response_model=List[CompetitionAdminResponse])
async def list_all_competitions(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """모든 대회 목록 (관리자 전용)"""
    result = await db.execute(
        select(Competition).order_by(Competition.created_at.desc())
    )
    competitions = result.scalars().all()

    return [
        CompetitionAdminResponse(
            id=str(comp.id),
            name=comp.name,
            description=comp.description,
            initial_balance=float(comp.initial_balance),
            fee_rate=float(comp.fee_rate),
            start_time=comp.start_time,
            end_time=comp.end_time,
            status=comp.status,
            created_at=comp.created_at
        )
        for comp in competitions
    ]


@router.post("/users/{user_id}/make-admin")
async def make_user_admin(
    user_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """사용자를 관리자로 승격 (관리자 전용)"""
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_admin = True
    await db.commit()

    return {"message": f"User {user.email} is now an admin"}


@router.get("/competitions/{competition_id}/participants", response_model=List[ParticipantAdminResponse])
async def get_competition_participants(
    competition_id: UUID,
    current_prices: Optional[str] = Query(None, description="현재 시세 JSON (예: {\"KRW-BTC\": 150000000})"),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """대회 참가자 목록 (실명 포함, 관리자 전용)"""
    import json

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

    initial_balance = float(comp.initial_balance)

    # 참가자 및 사용자 조회
    result = await db.execute(
        select(Participant, User)
        .join(User, Participant.user_id == User.id)
        .where(Participant.competition_id == competition_id)
        .order_by(Participant.joined_at.asc())
    )
    participants = result.all()

    response = []
    fee_rate = float(settings.FEE_RATE)

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

        balance = float(participant.balance)
        total_asset = balance + coin_value + pending_amount
        profit_rate = (total_asset - initial_balance) / initial_balance * 100

        # 주문 수 조회
        order_count_result = await db.execute(
            select(func.count()).select_from(Order).where(Order.participant_id == participant.id)
        )
        order_count = order_count_result.scalar() or 0

        # 거래 수 조회
        trade_count_result = await db.execute(
            select(func.count()).select_from(Trade).where(Trade.participant_id == participant.id)
        )
        trade_count = trade_count_result.scalar() or 0

        response.append(ParticipantAdminResponse(
            id=str(participant.id),
            user_id=str(user.id),
            email=user.email,
            username=user.username,
            balance=balance,
            coin_value=coin_value,
            total_asset=total_asset,
            profit_rate=profit_rate,
            joined_at=participant.joined_at,
            order_count=order_count,
            trade_count=trade_count
        ))

    # 수익률 순으로 정렬
    response.sort(key=lambda x: x.profit_rate, reverse=True)

    return response


@router.post("/competitions/{competition_id}/award")
async def award_participant(
    competition_id: UUID,
    request: AwardRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """참가자에게 상금 지급 (관리자 전용)

    실제 상금 지급은 외부에서 처리하고, 이 API는 기록 목적으로 사용합니다.
    """
    # 대회 조회
    result = await db.execute(
        select(Competition).where(Competition.id == competition_id)
    )
    comp = result.scalar_one_or_none()

    if not comp:
        raise HTTPException(status_code=404, detail="Competition not found")

    # 참가자 조회
    result = await db.execute(
        select(Participant, User)
        .join(User, Participant.user_id == User.id)
        .where(
            Participant.id == UUID(request.participant_id),
            Participant.competition_id == competition_id
        )
    )
    row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="Participant not found")

    participant, user = row

    return {
        "message": "상금 지급 기록 완료",
        "participant": {
            "id": str(participant.id),
            "email": user.email,
            "username": user.username
        },
        "amount": request.amount,
        "reason": request.reason,
        "competition": comp.name
    }


@router.put("/competitions/{competition_id}/full", response_model=CompetitionAdminResponse)
async def update_competition_full(
    competition_id: UUID,
    request: CompetitionUpdateFull,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """대회 전체 수정 (기간, 시작자금 등 포함, 관리자 전용)"""
    result = await db.execute(
        select(Competition).where(Competition.id == competition_id)
    )
    competition = result.scalar_one_or_none()

    if not competition:
        raise HTTPException(status_code=404, detail="Competition not found")

    # 상태 변경 검증
    if request.status:
        valid_statuses = ["pending", "active", "ended"]
        if request.status not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Must be one of: {valid_statuses}"
            )

    # 필드 업데이트
    if request.name is not None:
        competition.name = request.name
    if request.description is not None:
        competition.description = request.description
    if request.initial_balance is not None:
        competition.initial_balance = Decimal(str(request.initial_balance))
    if request.fee_rate is not None:
        competition.fee_rate = Decimal(str(request.fee_rate))
    if request.start_time is not None:
        competition.start_time = to_naive_utc(request.start_time)
    if request.end_time is not None:
        competition.end_time = to_naive_utc(request.end_time)
    if request.status is not None:
        competition.status = request.status

    # 시간 검증
    if competition.start_time >= competition.end_time:
        raise HTTPException(status_code=400, detail="end_time must be after start_time")

    await db.commit()
    await db.refresh(competition)

    # 참가자 수 조회
    count_result = await db.execute(
        select(func.count()).select_from(Participant).where(
            Participant.competition_id == competition.id
        )
    )
    participant_count = count_result.scalar() or 0

    return CompetitionAdminResponse(
        id=str(competition.id),
        name=competition.name,
        description=competition.description,
        initial_balance=float(competition.initial_balance),
        fee_rate=float(competition.fee_rate),
        start_time=competition.start_time,
        end_time=competition.end_time,
        status=competition.status,
        created_at=competition.created_at,
        participant_count=participant_count
    )


@router.get("/users", response_model=List[dict])
async def list_users(
    limit: int = Query(default=50, le=200),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """사용자 목록 (관리자 전용)"""
    result = await db.execute(
        select(User).order_by(User.created_at.desc()).limit(limit)
    )
    users = result.scalars().all()

    return [
        {
            "id": str(user.id),
            "email": user.email,
            "username": user.username,
            "is_admin": user.is_admin,
            "created_at": user.created_at.isoformat()
        }
        for user in users
    ]


@router.get("/stats")
async def get_admin_stats(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """관리자 통계 (관리자 전용)"""
    # 사용자 수
    user_count_result = await db.execute(select(func.count()).select_from(User))
    user_count = user_count_result.scalar() or 0

    # 대회 수
    competition_count_result = await db.execute(select(func.count()).select_from(Competition))
    competition_count = competition_count_result.scalar() or 0

    # 활성 대회
    active_comp_result = await db.execute(
        select(Competition).where(Competition.status == "active")
    )
    active_competition = active_comp_result.scalar_one_or_none()

    # 총 참가자 수
    participant_count_result = await db.execute(select(func.count()).select_from(Participant))
    participant_count = participant_count_result.scalar() or 0

    # 총 주문 수
    order_count_result = await db.execute(select(func.count()).select_from(Order))
    order_count = order_count_result.scalar() or 0

    # 총 거래 수
    trade_count_result = await db.execute(select(func.count()).select_from(Trade))
    trade_count = trade_count_result.scalar() or 0

    return {
        "users": user_count,
        "competitions": competition_count,
        "active_competition": {
            "id": str(active_competition.id),
            "name": active_competition.name
        } if active_competition else None,
        "participants": participant_count,
        "orders": order_count,
        "trades": trade_count
    }


@router.get("/participants/{participant_id}")
async def get_participant_detail(
    participant_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """참가자 상세 정보 조회 (관리자 전용)"""
    # 참가자 조회
    result = await db.execute(
        select(Participant, User, Competition)
        .join(User, Participant.user_id == User.id)
        .join(Competition, Participant.competition_id == Competition.id)
        .where(Participant.id == participant_id)
    )
    row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="Participant not found")

    participant, user, competition = row

    # 포지션 조회
    pos_result = await db.execute(
        select(Position).where(Position.participant_id == participant.id)
    )
    positions = pos_result.scalars().all()

    # 주문 수
    order_count_result = await db.execute(
        select(func.count()).select_from(Order).where(Order.participant_id == participant.id)
    )
    order_count = order_count_result.scalar() or 0

    # 거래 수
    trade_count_result = await db.execute(
        select(func.count()).select_from(Trade).where(Trade.participant_id == participant.id)
    )
    trade_count = trade_count_result.scalar() or 0

    return {
        "participant": {
            "id": str(participant.id),
            "balance": float(participant.balance),
            "joined_at": participant.joined_at.isoformat()
        },
        "user": {
            "id": str(user.id),
            "email": user.email,
            "username": user.username,
            "created_at": user.created_at.isoformat()
        },
        "competition": {
            "id": str(competition.id),
            "name": competition.name,
            "initial_balance": float(competition.initial_balance),
            "status": competition.status
        },
        "positions": [
            {
                "code": pos.code,
                "quantity": float(pos.quantity),
                "avg_buy_price": float(pos.avg_buy_price)
            }
            for pos in positions
        ],
        "stats": {
            "order_count": order_count,
            "trade_count": trade_count
        }
    }


@router.get("/participants/{participant_id}/orders")
async def get_participant_orders(
    participant_id: UUID,
    status: Optional[str] = None,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """참가자 주문 내역 조회 (관리자 전용)"""
    # 참가자 확인
    result = await db.execute(
        select(Participant).where(Participant.id == participant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Participant not found")

    # 주문 조회
    query = select(Order).where(Order.participant_id == participant_id)
    if status:
        query = query.where(Order.status == status)
    query = query.order_by(Order.created_at.desc()).offset(offset).limit(limit)

    result = await db.execute(query)
    orders = result.scalars().all()

    # 전체 개수
    count_query = select(func.count()).select_from(Order).where(Order.participant_id == participant_id)
    if status:
        count_query = count_query.where(Order.status == status)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "orders": [
            {
                "id": str(order.id),
                "code": order.code,
                "side": order.side,
                "order_type": order.order_type,
                "price": float(order.price) if order.price else None,
                "quantity": float(order.quantity),
                "filled_quantity": float(order.filled_quantity),
                "filled_price": float(order.filled_price) if order.filled_price else None,
                "fee": float(order.fee),
                "status": order.status,
                "created_at": order.created_at.isoformat(),
                "filled_at": order.filled_at.isoformat() if order.filled_at else None
            }
            for order in orders
        ]
    }


@router.get("/participants/{participant_id}/trades")
async def get_participant_trades(
    participant_id: UUID,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """참가자 거래 내역 조회 (관리자 전용)"""
    # 참가자 확인
    result = await db.execute(
        select(Participant).where(Participant.id == participant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Participant not found")

    # 거래 조회
    query = (
        select(Trade)
        .where(Trade.participant_id == participant_id)
        .order_by(Trade.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(query)
    trades = result.scalars().all()

    # 전체 개수
    total_result = await db.execute(
        select(func.count()).select_from(Trade).where(Trade.participant_id == participant_id)
    )
    total = total_result.scalar() or 0

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "trades": [
            {
                "id": str(trade.id),
                "code": trade.code,
                "side": trade.side,
                "price": float(trade.price),
                "quantity": float(trade.quantity),
                "total_amount": float(trade.total_amount),
                "fee": float(trade.fee),
                "created_at": trade.created_at.isoformat()
            }
            for trade in trades
        ]
    }


@router.get("/corrupted-orders")
async def find_corrupted_orders(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """비정상적인 체결가가 기록된 주문 찾기 (관리자 전용)"""
    # 체결된 모든 주문 조회
    result = await db.execute(
        select(Order, Participant, User, Competition)
        .join(Participant, Order.participant_id == Participant.id)
        .join(User, Participant.user_id == User.id)
        .join(Competition, Participant.competition_id == Competition.id)
        .where(
            Order.status == "filled",
            Order.filled_price.isnot(None)
        )
        .order_by(Order.created_at.desc())
    )
    all_orders = result.all()

    corrupted = []
    for order, participant, user, competition in all_orders:
        filled_price = float(order.filled_price) if order.filled_price else 0

        # 가격 범위 검증
        if order.code in PRICE_RANGES:
            min_price, max_price = PRICE_RANGES[order.code]
            # 범위의 10배 밖이면 비정상
            if filled_price < min_price * 0.1 or filled_price > max_price * 10:
                corrupted.append({
                    "order_id": str(order.id),
                    "code": order.code,
                    "side": order.side,
                    "order_type": order.order_type,
                    "filled_price": filled_price,
                    "expected_range": f"{min_price*0.1:,.0f} ~ {max_price*10:,.0f}",
                    "quantity": float(order.quantity),
                    "total_amount": filled_price * float(order.quantity),
                    "fee": float(order.fee),
                    "created_at": order.created_at.isoformat(),
                    "user_email": user.email,
                    "competition_name": competition.name
                })

    return {
        "total_checked": len(all_orders),
        "corrupted_count": len(corrupted),
        "corrupted_orders": corrupted
    }


class FixOrderRequest(BaseModel):
    """주문 수정 요청"""
    correct_price: float


@router.put("/corrupted-orders/{order_id}")
async def fix_corrupted_order(
    order_id: UUID,
    request: FixOrderRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """비정상 주문의 체결가를 올바른 가격으로 수정 (관리자 전용)

    잔고, 포지션, 거래 내역 모두 올바르게 조정됩니다.
    """
    correct_price = Decimal(str(request.correct_price))

    # 수정할 가격 유효성 검증
    result = await db.execute(
        select(Order, Participant, Trade)
        .join(Participant, Order.participant_id == Participant.id)
        .outerjoin(Trade, Trade.order_id == Order.id)
        .where(Order.id == order_id)
    )
    rows = result.all()

    if not rows:
        raise HTTPException(status_code=404, detail="Order not found")

    order, participant, trade = rows[0]

    if order.status != "filled":
        raise HTTPException(status_code=400, detail="Only filled orders can be fixed")

    # 수정할 가격이 유효한지 확인
    if not validate_price(order.code, correct_price):
        raise HTTPException(
            status_code=400,
            detail=f"The correct_price {correct_price} is also invalid for {order.code}"
        )

    old_price = Decimal(str(order.filled_price)) if order.filled_price else Decimal("0")
    quantity = Decimal(str(order.quantity))
    fee_rate = Decimal(str(0.0005))  # 0.05%

    # 이전 금액 계산
    old_total = old_price * quantity
    old_fee = old_total * fee_rate

    # 새 금액 계산
    new_total = correct_price * quantity
    new_fee = new_total * fee_rate

    # 잔고 조정
    if order.side == "buy":
        # 매수: 이전에 (old_total + old_fee)를 지불, 새로 (new_total + new_fee)를 지불해야 함
        # 차액 = (old_total + old_fee) - (new_total + new_fee)
        # 양수면 환불, 음수면 추가 차감
        balance_diff = (old_total + old_fee) - (new_total + new_fee)
        participant.balance = Decimal(str(participant.balance)) + balance_diff

        # 평균 매수가 조정 (해당 코인 포지션)
        pos_result = await db.execute(
            select(Position).where(
                Position.participant_id == participant.id,
                Position.code == order.code
            )
        )
        position = pos_result.scalar_one_or_none()
        if position:
            # 평균단가 재계산 (단순화: 이 주문의 가격만 반영)
            # 정확한 계산을 위해서는 모든 매수 주문을 다시 계산해야 하지만,
            # 여기서는 이 주문의 기여분만 조정
            old_contribution = old_price * quantity
            new_contribution = correct_price * quantity
            total_value = Decimal(str(position.quantity)) * Decimal(str(position.avg_buy_price))

            # 이전 기여 제거 후 새 기여 추가
            adjusted_total = total_value - old_contribution + new_contribution
            if position.quantity > 0:
                position.avg_buy_price = adjusted_total / Decimal(str(position.quantity))

    else:  # sell
        # 매도: 이전에 (old_total - old_fee)를 받음, 새로 (new_total - new_fee)를 받아야 함
        # 차액 = (new_total - new_fee) - (old_total - old_fee)
        # 양수면 추가 지급, 음수면 환수
        balance_diff = (new_total - new_fee) - (old_total - old_fee)
        participant.balance = Decimal(str(participant.balance)) + balance_diff

    # 주문 업데이트
    order.filled_price = correct_price
    order.fee = new_fee

    # 거래 내역 업데이트
    if trade:
        trade.price = correct_price
        trade.total_amount = new_total
        trade.fee = new_fee

    await db.commit()

    return {
        "message": f"Order {order_id} fixed successfully",
        "order": {
            "id": str(order.id),
            "code": order.code,
            "side": order.side,
            "old_filled_price": float(old_price),
            "new_filled_price": float(correct_price),
            "quantity": float(quantity),
            "old_total": float(old_total),
            "new_total": float(new_total),
            "old_fee": float(old_fee),
            "new_fee": float(new_fee)
        },
        "participant": {
            "id": str(participant.id),
            "new_balance": float(participant.balance)
        }
    }


@router.delete("/corrupted-orders/{order_id}")
async def delete_corrupted_order(
    order_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """비정상 주문 삭제 및 잔고/포지션 복구 (관리자 전용)

    주의: 이 작업은 되돌릴 수 없습니다. 신중하게 사용하세요.
    """
    # 주문 조회
    result = await db.execute(
        select(Order, Participant)
        .join(Participant, Order.participant_id == Participant.id)
        .where(Order.id == order_id)
    )
    row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="Order not found")

    order, participant = row

    if order.status != "filled":
        raise HTTPException(status_code=400, detail="Only filled orders can be deleted")

    filled_price = float(order.filled_price) if order.filled_price else 0

    # 가격 유효성 검증
    if order.code in PRICE_RANGES:
        min_price, max_price = PRICE_RANGES[order.code]
        if min_price * 0.1 <= filled_price <= max_price * 10:
            raise HTTPException(
                status_code=400,
                detail="This order has a valid price. Only corrupted orders can be deleted."
            )

    # 관련 거래 내역 삭제
    await db.execute(
        Trade.__table__.delete().where(Trade.order_id == order_id)
    )

    # 잔고/포지션 복구 시도 (부정확할 수 있음 - 단순 복구)
    quantity = Decimal(str(order.quantity))
    fee = Decimal(str(order.fee))
    total_amount = Decimal(str(filled_price)) * quantity

    if order.side == "buy":
        # 매수였던 경우: 잔고 복구 (지불한 금액 + 수수료), 포지션 차감
        restore_balance = total_amount + fee
        participant.balance = Decimal(str(participant.balance)) + restore_balance

        # 포지션 차감
        pos_result = await db.execute(
            select(Position).where(
                Position.participant_id == participant.id,
                Position.code == order.code
            )
        )
        position = pos_result.scalar_one_or_none()
        if position:
            new_quantity = Decimal(str(position.quantity)) - quantity
            if new_quantity <= 0:
                await db.delete(position)
            else:
                position.quantity = new_quantity
    else:
        # 매도였던 경우: 잔고 차감 (받은 금액 - 수수료), 포지션 복구
        received = total_amount - fee
        participant.balance = Decimal(str(participant.balance)) - received

        # 포지션 복구
        pos_result = await db.execute(
            select(Position).where(
                Position.participant_id == participant.id,
                Position.code == order.code
            )
        )
        position = pos_result.scalar_one_or_none()
        if position:
            position.quantity = Decimal(str(position.quantity)) + quantity
        else:
            # 포지션이 없으면 새로 생성 (평균단가는 정확하지 않음)
            new_position = Position(
                participant_id=participant.id,
                code=order.code,
                quantity=quantity,
                avg_buy_price=Decimal("0")  # 정확한 값을 알 수 없음
            )
            db.add(new_position)

    # 주문 삭제
    await db.delete(order)
    await db.commit()

    return {
        "message": f"Corrupted order {order_id} deleted",
        "restored_balance": str(participant.balance),
        "note": "Position was adjusted. Average buy price may be inaccurate."
    }


class DeleteDuplicateOrdersRequest(BaseModel):
    """중복 주문 삭제 요청"""
    order_ids: List[str]


@router.post("/duplicate-orders/delete")
async def delete_duplicate_orders(
    request: DeleteDuplicateOrdersRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """중복 주문 삭제 및 잔고/포지션 복구 (관리자 전용)

    버튼 스팸 등으로 인해 100ms 이내에 동일 조건으로 생성된 중복 주문을 삭제합니다.
    주의: 이 작업은 되돌릴 수 없습니다. 신중하게 사용하세요.
    """
    deleted_orders = []
    errors = []

    for order_id_str in request.order_ids:
        try:
            order_id = UUID(order_id_str)

            # 주문 조회
            result = await db.execute(
                select(Order, Participant)
                .join(Participant, Order.participant_id == Participant.id)
                .where(Order.id == order_id)
            )
            row = result.first()

            if not row:
                errors.append({"order_id": order_id_str, "error": "Order not found"})
                continue

            order, participant = row

            if order.status != "filled":
                errors.append({"order_id": order_id_str, "error": "Only filled orders can be deleted"})
                continue

            # 잔고/포지션 복구
            quantity = Decimal(str(order.quantity))
            fee = Decimal(str(order.fee))
            filled_price = Decimal(str(order.filled_price)) if order.filled_price else Decimal("0")
            total_amount = filled_price * quantity

            balance_change = Decimal("0")

            if order.side == "buy":
                # 매수: 잔고 복구 (지불금액 + 수수료), 포지션 차감
                restore_balance = total_amount + fee
                balance_change = restore_balance
                participant.balance = Decimal(str(participant.balance)) + restore_balance

                # 포지션 차감
                pos_result = await db.execute(
                    select(Position).where(
                        Position.participant_id == participant.id,
                        Position.code == order.code
                    )
                )
                position = pos_result.scalar_one_or_none()
                if position:
                    new_quantity = Decimal(str(position.quantity)) - quantity
                    if new_quantity <= 0:
                        await db.delete(position)
                    else:
                        position.quantity = new_quantity
            else:
                # 매도: 잔고 차감 (받은금액 - 수수료), 포지션 복구
                received = total_amount - fee
                balance_change = -received
                participant.balance = Decimal(str(participant.balance)) - received

                # 포지션 복구
                pos_result = await db.execute(
                    select(Position).where(
                        Position.participant_id == participant.id,
                        Position.code == order.code
                    )
                )
                position = pos_result.scalar_one_or_none()
                if position:
                    position.quantity = Decimal(str(position.quantity)) + quantity

            # 관련 거래 내역 삭제
            await db.execute(
                Trade.__table__.delete().where(Trade.order_id == order_id)
            )

            # 주문 삭제
            await db.delete(order)

            deleted_orders.append({
                "order_id": order_id_str,
                "code": order.code,
                "side": order.side,
                "quantity": float(quantity),
                "filled_price": float(filled_price),
                "balance_change": float(balance_change)
            })

        except Exception as e:
            errors.append({"order_id": order_id_str, "error": str(e)})

    await db.commit()

    # 최종 잔고 조회
    final_balance = None
    if deleted_orders:
        # 첫 번째 삭제된 주문의 참가자 잔고 조회
        first_order_id = UUID(request.order_ids[0])
        result = await db.execute(
            select(Participant)
            .join(Order, Order.participant_id == Participant.id)
            .where(Order.id == first_order_id)
        )
        # 이미 삭제되어서 조회 안 될 수 있음, 대신 deleted_orders에서 participant_id 활용
        pass

    return {
        "message": f"Deleted {len(deleted_orders)} duplicate orders",
        "deleted_count": len(deleted_orders),
        "error_count": len(errors),
        "deleted_orders": deleted_orders,
        "errors": errors,
        "total_balance_restored": sum(o["balance_change"] for o in deleted_orders)
    }


def _group_key(order: Order):
    """중복 주문 그룹화 키 생성"""
    return (
        order.code,
        order.side,
        order.order_type,
        str(order.quantity),
        str(order.filled_price) if order.filled_price else None
    )


def _find_duplicate_groups(orders: list):
    """
    시간순으로 정렬된 주문에서 중복 그룹 찾기

    중복 기준:
    - 100ms(0.1초) 이내에 발생
    - 동일한 코인, side, order_type, 수량, 체결가

    이런 패턴은 버튼 더블클릭/스팸 버그로 인한 것으로 판단
    """
    duplicate_groups = []

    i = 0
    while i < len(orders):
        order = orders[i]

        # 체결된 주문만 대상
        if order.status != "filled":
            i += 1
            continue

        # 같은 그룹 찾기
        group = [order]
        key = _group_key(order)

        j = i + 1
        while j < len(orders):
            next_order = orders[j]

            if next_order.status != "filled":
                j += 1
                continue

            # 시간 차이가 100ms(0.1초) 이내이고 같은 조건이면 중복
            time_diff = abs((next_order.created_at - order.created_at).total_seconds())

            if time_diff <= 0.1 and _group_key(next_order) == key:
                group.append(next_order)
                j += 1
            elif time_diff > 0.1:
                break
            else:
                j += 1

        if len(group) > 1:
            duplicate_groups.append(group)
            i = j
        else:
            i += 1

    return duplicate_groups


@router.post("/participants/{participant_id}/fix-duplicates")
async def fix_participant_duplicates(
    participant_id: UUID,
    dry_run: bool = Query(default=True, description="True면 시뮬레이션만, False면 실제 수정"),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """참가자의 중복 주문을 자동으로 분석하고 수정 (관리자 전용)

    100ms 이내에 동일 조건으로 발생한 중복 주문을 찾아:
    - 첫 번째 주문만 유지
    - 나머지 중복 주문 삭제
    - 잔고 및 포지션 복구

    Args:
        participant_id: 참가자 UUID
        dry_run: True면 분석만, False면 실제 수정 (기본: True)
    """
    # 참가자 조회
    result = await db.execute(
        select(Participant).where(Participant.id == participant_id)
    )
    participant = result.scalar_one_or_none()

    if not participant:
        raise HTTPException(status_code=404, detail="Participant not found")

    original_balance = float(participant.balance)

    # 모든 주문 조회 (시간순)
    result = await db.execute(
        select(Order)
        .where(Order.participant_id == participant_id)
        .order_by(Order.created_at.asc())
    )
    orders = list(result.scalars().all())

    # 중복 그룹 찾기
    duplicate_groups = _find_duplicate_groups(orders)

    if not duplicate_groups:
        return {
            "message": "중복 주문이 없습니다",
            "participant_id": str(participant_id),
            "current_balance": original_balance,
            "total_orders": len(orders),
            "duplicate_groups": 0,
            "orders_to_delete": 0,
            "dry_run": dry_run
        }

    # 삭제할 주문 목록 생성
    orders_to_delete = []
    total_balance_change = Decimal("0")

    for group in duplicate_groups:
        keep = group[0]  # 첫 번째 유지
        to_delete = group[1:]  # 나머지 삭제

        group_info = {
            "keep_order_id": str(keep.id),
            "code": keep.code,
            "side": keep.side,
            "quantity": float(keep.quantity),
            "filled_price": float(keep.filled_price) if keep.filled_price else 0,
            "created_at": keep.created_at.isoformat(),
            "delete_orders": []
        }

        for order in to_delete:
            quantity = Decimal(str(order.quantity))
            fee = Decimal(str(order.fee))
            filled_price = Decimal(str(order.filled_price)) if order.filled_price else Decimal("0")
            total_amount = filled_price * quantity

            if order.side == "buy":
                balance_change = total_amount + fee
            else:
                balance_change = -(total_amount - fee)

            total_balance_change += balance_change

            delete_info = {
                "order_id": str(order.id),
                "balance_change": float(balance_change)
            }
            group_info["delete_orders"].append(delete_info)

            if not dry_run:
                # 실제 삭제 수행
                if order.side == "buy":
                    # 매수: 잔고 복구, 포지션 차감
                    participant.balance = Decimal(str(participant.balance)) + (total_amount + fee)

                    pos_result = await db.execute(
                        select(Position).where(
                            Position.participant_id == participant.id,
                            Position.code == order.code
                        )
                    )
                    position = pos_result.scalar_one_or_none()
                    if position:
                        new_qty = Decimal(str(position.quantity)) - quantity
                        if new_qty <= 0:
                            await db.delete(position)
                        else:
                            position.quantity = new_qty
                else:
                    # 매도: 잔고 차감, 포지션 복구
                    participant.balance = Decimal(str(participant.balance)) - (total_amount - fee)

                    pos_result = await db.execute(
                        select(Position).where(
                            Position.participant_id == participant.id,
                            Position.code == order.code
                        )
                    )
                    position = pos_result.scalar_one_or_none()
                    if position:
                        position.quantity = Decimal(str(position.quantity)) + quantity

                # 거래 내역 삭제
                await db.execute(
                    Trade.__table__.delete().where(Trade.order_id == order.id)
                )
                # 주문 삭제
                await db.delete(order)

        orders_to_delete.append(group_info)

    if not dry_run:
        await db.commit()
        await db.refresh(participant)

    total_deleted = sum(len(g["delete_orders"]) for g in orders_to_delete)

    return {
        "message": "중복 주문 수정 완료" if not dry_run else "중복 주문 분석 완료 (dry_run)",
        "participant_id": str(participant_id),
        "dry_run": dry_run,
        "original_balance": original_balance,
        "new_balance": float(participant.balance),
        "total_balance_change": float(total_balance_change),
        "total_orders": len(orders),
        "duplicate_groups": len(duplicate_groups),
        "orders_deleted": total_deleted,
        "details": orders_to_delete
    }
