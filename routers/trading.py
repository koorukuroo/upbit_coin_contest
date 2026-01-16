"""트레이딩 라우터"""
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from decimal import Decimal
import logging
from pydantic import BaseModel, field_validator

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import clickhouse_connect

from database import get_db
from models.api_key import ApiKey
from models.participant import Participant
from models.position import Position
from models.order import Order
from models.trade import Trade
from models.competition import Competition
from middleware.api_key_auth import verify_api_key
from services.order_service import OrderService, MAX_PRICE_DEVIATION
from config import settings
from cache import get_cache

logger = logging.getLogger(__name__)


def validate_competition_time(competition: Competition) -> None:
    """대회 시간이 유효한지 검증

    Args:
        competition: 대회 객체

    Raises:
        HTTPException: 대회 시간이 아닌 경우
    """
    now = datetime.utcnow()

    if now < competition.start_time:
        raise HTTPException(
            status_code=400,
            detail=f"대회가 아직 시작되지 않았습니다. 시작 시간: {competition.start_time.isoformat()}Z"
        )

    if now > competition.end_time:
        raise HTTPException(
            status_code=400,
            detail=f"대회가 종료되었습니다. 종료 시간: {competition.end_time.isoformat()}Z"
        )


# 시장가 검증을 위한 ClickHouse 클라이언트
_ch_client = None

def get_ch_client():
    """ClickHouse 클라이언트 싱글톤"""
    global _ch_client
    if _ch_client is None:
        _ch_client = clickhouse_connect.get_client(
            host=settings.CLICKHOUSE_HOST,
            port=settings.CLICKHOUSE_PORT,
            username=settings.CLICKHOUSE_USER,
            password=settings.CLICKHOUSE_PASSWORD,
            database=settings.CLICKHOUSE_DATABASE
        )
    return _ch_client


async def get_server_market_price(code: str) -> Optional[Decimal]:
    """서버에서 현재 시장가 조회 (ClickHouse)"""
    try:
        client = get_ch_client()
        result = client.query(f"""
            SELECT trade_price
            FROM upbit_ticker
            WHERE code = '{code}'
            ORDER BY timestamp DESC
            LIMIT 1
        """)

        if result.result_rows:
            return Decimal(str(result.result_rows[0][0]))
        return None
    except Exception as e:
        logger.error(f"Failed to get market price for {code}: {e}")
        return None


def validate_client_price(client_price: Decimal, server_price: Decimal, code: str) -> bool:
    """클라이언트 제공 가격이 서버 시장가와 합리적인 범위 내인지 검증

    Returns:
        True if valid, raises HTTPException if invalid
    """
    if server_price <= 0:
        logger.warning(f"Invalid server price for {code}: {server_price}")
        return True  # 서버 가격 조회 실패 시 통과 (failsafe)

    deviation = abs(client_price - server_price) / server_price

    if deviation > MAX_PRICE_DEVIATION:
        logger.error(
            f"Client price validation failed for {code}: "
            f"client_price={client_price}, server_price={server_price}, "
            f"deviation={deviation:.2%} (max allowed: {MAX_PRICE_DEVIATION:.0%})"
        )
        raise HTTPException(
            status_code=400,
            detail=f"Price mismatch: provided {float(client_price):,.0f} but market is {float(server_price):,.0f}. "
                   f"Deviation {deviation:.1%} exceeds {MAX_PRICE_DEVIATION:.0%} limit."
        )

    return True

router = APIRouter()


# ============ 스키마 ============

class BalanceResponse(BaseModel):
    """잔고 응답"""
    balance: float
    competition_id: str
    competition_name: str


class PositionResponse(BaseModel):
    """포지션 응답"""
    code: str
    quantity: float
    avg_buy_price: float
    total_value: float

    class Config:
        from_attributes = True


class OrderCreate(BaseModel):
    """주문 생성 요청"""
    code: str
    side: str  # buy, sell
    order_type: str  # market, limit
    quantity: float
    price: Optional[float] = None  # 지정가 주문 시 필수
    idempotency_key: Optional[str] = None  # 중복 주문 방지용 키

    @field_validator("side")
    @classmethod
    def validate_side(cls, v):
        if v not in ["buy", "sell"]:
            raise ValueError("side must be 'buy' or 'sell'")
        return v

    @field_validator("order_type")
    @classmethod
    def validate_order_type(cls, v):
        if v not in ["market", "limit"]:
            raise ValueError("order_type must be 'market' or 'limit'")
        return v

    @field_validator("code")
    @classmethod
    def validate_code(cls, v):
        if v not in settings.SUPPORTED_CODES:
            raise ValueError(f"Unsupported code. Supported: {settings.SUPPORTED_CODES}")
        return v


class OrderResponse(BaseModel):
    """주문 응답"""
    id: str
    code: str
    side: str
    order_type: str
    price: Optional[float]
    quantity: float
    filled_quantity: float
    filled_price: Optional[float]
    fee: float
    status: str
    created_at: datetime
    filled_at: Optional[datetime]

    class Config:
        from_attributes = True


class TradeResponse(BaseModel):
    """거래 내역 응답"""
    id: str
    code: str
    side: str
    price: float
    quantity: float
    total_amount: float
    fee: float
    created_at: datetime

    class Config:
        from_attributes = True


# ============ 엔드포인트 ============

@router.get("/balance", response_model=BalanceResponse)
async def get_balance(
    api_key: ApiKey = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db)
):
    """잔고 조회 (활성 대회)"""
    result = await db.execute(
        select(Participant, Competition)
        .join(Competition, Participant.competition_id == Competition.id)
        .where(
            Participant.user_id == api_key.user_id,
            Competition.status == "active"
        )
    )
    row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="Not participating in active competition")

    participant, competition = row

    return BalanceResponse(
        balance=float(participant.balance),
        competition_id=str(competition.id),
        competition_name=competition.name
    )


@router.get("/positions", response_model=List[PositionResponse])
async def get_positions(
    api_key: ApiKey = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db)
):
    """보유 포지션 조회"""
    # 참가자 조회 (여러 active 대회 중 참가한 대회)
    result = await db.execute(
        select(Participant)
        .join(Competition, Participant.competition_id == Competition.id)
        .where(
            Participant.user_id == api_key.user_id,
            Competition.status == "active"
        )
        .limit(1)
    )
    participant = result.scalars().first()

    if not participant:
        raise HTTPException(status_code=404, detail="Not participating in active competition")

    # 포지션 조회
    result = await db.execute(
        select(Position).where(Position.participant_id == participant.id)
    )
    positions = result.scalars().all()

    return [
        PositionResponse(
            code=pos.code,
            quantity=float(pos.quantity),
            avg_buy_price=float(pos.avg_buy_price),
            total_value=float(pos.quantity) * float(pos.avg_buy_price)
        )
        for pos in positions
    ]


async def _execute_order(
    order_service: OrderService,
    api_key: ApiKey,
    order_data: OrderCreate,
    validated_price: Decimal
) -> Order:
    """주문 실행 (락 내부에서 호출)"""
    # 참가자 조회
    participant = await order_service.get_participant(api_key.user_id)

    if order_data.order_type == "market":
        return await order_service.create_market_order(
            participant=participant,
            code=order_data.code,
            side=order_data.side,
            quantity=Decimal(str(order_data.quantity)),
            current_price=validated_price
        )
    else:  # limit
        return await order_service.create_limit_order(
            participant=participant,
            code=order_data.code,
            side=order_data.side,
            quantity=Decimal(str(order_data.quantity)),
            price=Decimal(str(order_data.price)),
            current_price=validated_price
        )


@router.post("/orders", response_model=OrderResponse)
async def create_order(
    order_data: OrderCreate,
    current_price: float = Query(..., description="현재 시세 (시장가 주문 시 필수)"),
    api_key: ApiKey = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db)
):
    """주문 생성

    - 시장가 주문: current_price로 즉시 체결
    - 지정가 주문: price에 도달하면 체결 (대기)

    Note: 클라이언트가 제공한 current_price는 서버의 실제 시장가와 비교 검증됩니다.
    시장가 대비 ±10% 이상 차이나면 주문이 거부됩니다.

    중복 주문 방지: idempotency_key를 제공하면 5초 내 동일 키로 중복 주문 방지
    """
    # 대회 시간 검증 (시작 전/종료 후 주문 차단)
    result = await db.execute(
        select(Competition)
        .join(Participant, Participant.competition_id == Competition.id)
        .where(
            Participant.user_id == api_key.user_id,
            Competition.status == "active"
        )
    )
    competition = result.scalar_one_or_none()

    if not competition:
        raise HTTPException(status_code=404, detail="Not participating in active competition")

    validate_competition_time(competition)

    # 중복 주문 방지 체크
    cache = await get_cache()
    if cache and order_data.idempotency_key:
        # idempotency_key가 제공된 경우 중복 체크
        cache_key = f"order:idempotency:{api_key.user_id}:{order_data.idempotency_key}"
        is_new = await cache.setnx_with_ttl(cache_key, "1", ttl=5)
        if not is_new:
            raise HTTPException(
                status_code=409,
                detail="Duplicate order detected. Please wait before retrying."
            )
    elif cache:
        # idempotency_key가 없으면 주문 내용 기반 중복 체크 (2초 TTL)
        order_hash = f"{api_key.user_id}:{order_data.code}:{order_data.side}:{order_data.order_type}:{order_data.quantity}:{order_data.price}"
        cache_key = f"order:hash:{order_hash}"
        is_new = await cache.setnx_with_ttl(cache_key, "1", ttl=2)
        if not is_new:
            raise HTTPException(
                status_code=409,
                detail="Duplicate order detected (same order within 2 seconds). "
                       "Use idempotency_key to prevent this."
            )

    # 지정가 주문인데 가격 없음
    if order_data.order_type == "limit" and not order_data.price:
        raise HTTPException(status_code=400, detail="price is required for limit orders")

    # 서버측 시장가 검증
    client_price = Decimal(str(current_price))
    server_price = await get_server_market_price(order_data.code)

    if server_price:
        # 클라이언트 가격이 서버 시장가와 합리적 범위 내인지 검증
        validate_client_price(client_price, server_price, order_data.code)
        # 검증 통과 시 서버 가격 사용 (더 신뢰할 수 있음)
        validated_price = server_price
        logger.info(
            f"Price validated for {order_data.code}: "
            f"client={float(client_price):,.0f}, server={float(server_price):,.0f}, "
            f"using server price"
        )
    else:
        # 서버 가격 조회 실패 시 클라이언트 가격 사용 (fallback)
        validated_price = client_price
        logger.warning(
            f"Server price unavailable for {order_data.code}, "
            f"using client price: {float(client_price):,.0f}"
        )

    order_service = OrderService(db)

    # 분산 락으로 동일 사용자의 동시 주문 방지
    lock_name = f"order:{api_key.user_id}"

    try:
        if cache:
            async with cache.distributed_lock(lock_name, ttl=10, wait_timeout=5.0):
                order = await _execute_order(order_service, api_key, order_data, validated_price)
        else:
            # Redis 없으면 락 없이 실행
            order = await _execute_order(order_service, api_key, order_data, validated_price)
    except TimeoutError:
        raise HTTPException(
            status_code=429,
            detail="Too many concurrent requests. Please try again."
        )

    return OrderResponse(
        id=str(order.id),
        code=order.code,
        side=order.side,
        order_type=order.order_type,
        price=float(order.price) if order.price else None,
        quantity=float(order.quantity),
        filled_quantity=float(order.filled_quantity),
        filled_price=float(order.filled_price) if order.filled_price else None,
        fee=float(order.fee),
        status=order.status,
        created_at=order.created_at,
        filled_at=order.filled_at
    )


@router.get("/orders", response_model=List[OrderResponse])
async def list_orders(
    status: Optional[str] = None,
    limit: int = Query(default=50, le=100),
    api_key: ApiKey = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db)
):
    """주문 내역 조회"""
    # 참가자 조회 (여러 active 대회 중 참가한 대회)
    result = await db.execute(
        select(Participant)
        .join(Competition, Participant.competition_id == Competition.id)
        .where(
            Participant.user_id == api_key.user_id,
            Competition.status == "active"
        )
        .limit(1)
    )
    participant = result.scalars().first()

    if not participant:
        raise HTTPException(status_code=404, detail="Not participating in active competition")

    # 주문 조회
    query = select(Order).where(Order.participant_id == participant.id)
    if status:
        query = query.where(Order.status == status)
    query = query.order_by(Order.created_at.desc()).limit(limit)

    result = await db.execute(query)
    orders = result.scalars().all()

    return [
        OrderResponse(
            id=str(order.id),
            code=order.code,
            side=order.side,
            order_type=order.order_type,
            price=float(order.price) if order.price else None,
            quantity=float(order.quantity),
            filled_quantity=float(order.filled_quantity),
            filled_price=float(order.filled_price) if order.filled_price else None,
            fee=float(order.fee),
            status=order.status,
            created_at=order.created_at,
            filled_at=order.filled_at
        )
        for order in orders
    ]


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: UUID,
    api_key: ApiKey = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db)
):
    """주문 상세 조회"""
    result = await db.execute(
        select(Order, Participant)
        .join(Participant, Order.participant_id == Participant.id)
        .where(
            Order.id == order_id,
            Participant.user_id == api_key.user_id
        )
    )
    row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="Order not found")

    order, _ = row

    return OrderResponse(
        id=str(order.id),
        code=order.code,
        side=order.side,
        order_type=order.order_type,
        price=float(order.price) if order.price else None,
        quantity=float(order.quantity),
        filled_quantity=float(order.filled_quantity),
        filled_price=float(order.filled_price) if order.filled_price else None,
        fee=float(order.fee),
        status=order.status,
        created_at=order.created_at,
        filled_at=order.filled_at
    )


@router.delete("/orders/{order_id}", response_model=OrderResponse)
async def cancel_order(
    order_id: UUID,
    api_key: ApiKey = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db)
):
    """주문 취소 (지정가 주문만)"""
    result = await db.execute(
        select(Order, Participant)
        .join(Participant, Order.participant_id == Participant.id)
        .where(
            Order.id == order_id,
            Participant.user_id == api_key.user_id
        )
    )
    row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="Order not found")

    order, _ = row

    order_service = OrderService(db)
    cancelled_order = await order_service.cancel_order(order)

    return OrderResponse(
        id=str(cancelled_order.id),
        code=cancelled_order.code,
        side=cancelled_order.side,
        order_type=cancelled_order.order_type,
        price=float(cancelled_order.price) if cancelled_order.price else None,
        quantity=float(cancelled_order.quantity),
        filled_quantity=float(cancelled_order.filled_quantity),
        filled_price=float(cancelled_order.filled_price) if cancelled_order.filled_price else None,
        fee=float(cancelled_order.fee),
        status=cancelled_order.status,
        created_at=cancelled_order.created_at,
        filled_at=cancelled_order.filled_at
    )


@router.get("/trades", response_model=List[TradeResponse])
async def list_trades(
    limit: int = Query(default=50, le=100),
    api_key: ApiKey = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db)
):
    """거래 내역 조회"""
    # 참가자 조회 (여러 active 대회 중 참가한 대회)
    result = await db.execute(
        select(Participant)
        .join(Competition, Participant.competition_id == Competition.id)
        .where(
            Participant.user_id == api_key.user_id,
            Competition.status == "active"
        )
        .limit(1)
    )
    participant = result.scalars().first()

    if not participant:
        raise HTTPException(status_code=404, detail="Not participating in active competition")

    # 거래 내역 조회
    result = await db.execute(
        select(Trade)
        .where(Trade.participant_id == participant.id)
        .order_by(Trade.created_at.desc())
        .limit(limit)
    )
    trades = result.scalars().all()

    return [
        TradeResponse(
            id=str(trade.id),
            code=trade.code,
            side=trade.side,
            price=float(trade.price),
            quantity=float(trade.quantity),
            total_amount=float(trade.total_amount),
            fee=float(trade.fee),
            created_at=trade.created_at
        )
        for trade in trades
    ]
