"""주문 처리 서비스"""
from decimal import Decimal
from datetime import datetime
from typing import Optional
from uuid import UUID
import logging

from sqlalchemy import select, update, delete, text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from models.participant import Participant
from models.position import Position
from models.order import Order
from models.trade import Trade
from models.competition import Competition
from config import settings

logger = logging.getLogger(__name__)

# 시장가 대비 허용 가격 변동폭 (±10%)
MAX_PRICE_DEVIATION = Decimal("0.10")

# 코인별 대략적인 가격 범위 (KRW) - 가격 유효성 검증용
# 범위를 벗어나면 경고/거부 (±90% 허용)
PRICE_RANGES = {
    "KRW-BTC": (50_000_000, 200_000_000),    # 5천만 ~ 2억
    "KRW-ETH": (2_000_000, 10_000_000),       # 200만 ~ 1천만
    "KRW-XRP": (300, 5_000),                   # 300 ~ 5천
    "KRW-SOL": (50_000, 500_000),              # 5만 ~ 50만
    "KRW-DOGE": (100, 2_000),                  # 100 ~ 2천
    "KRW-ADA": (200, 3_000),                   # 200 ~ 3천
    "KRW-AVAX": (10_000, 200_000),             # 1만 ~ 20만
    "KRW-DOT": (3_000, 50_000),                # 3천 ~ 5만
    "KRW-LINK": (5_000, 100_000),              # 5천 ~ 10만
    "KRW-MATIC": (200, 5_000),                 # 200 ~ 5천
}

def validate_price(code: str, price: Decimal) -> bool:
    """가격이 합리적인 범위 내인지 검증 (기본 범위 검증)"""
    if code not in PRICE_RANGES:
        return True  # 범위 정의 없으면 통과

    min_price, max_price = PRICE_RANGES[code]
    price_float = float(price)

    # 범위의 2배까지만 허용 (기존 10배에서 강화)
    if price_float < min_price * 0.5 or price_float > max_price * 2:
        logger.error(f"Price validation failed: {code} price {price_float} out of range [{min_price*0.5}, {max_price*2}]")
        return False

    return True


def validate_price_against_market(code: str, order_price: Decimal, market_price: Decimal) -> bool:
    """주문 가격이 시장가 대비 합리적인 범위인지 검증

    시장가 대비 ±10% 범위 내에서만 거래 허용
    """
    if market_price <= 0:
        logger.warning(f"Invalid market price for {code}: {market_price}")
        return False

    deviation = abs(order_price - market_price) / market_price

    if deviation > MAX_PRICE_DEVIATION:
        logger.error(
            f"Price deviation too large for {code}: "
            f"order_price={order_price}, market_price={market_price}, "
            f"deviation={deviation:.2%} (max allowed: {MAX_PRICE_DEVIATION:.0%})"
        )
        return False

    return True


class OrderService:
    """주문 처리 서비스"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_participant(self, user_id: UUID, competition_id: Optional[UUID] = None) -> Participant:
        """참가자 조회 (활성 대회 중 참가한 대회)"""
        query = select(Participant).join(Competition).where(
            Participant.user_id == user_id,
            Competition.status == "active"
        )
        if competition_id:
            query = query.where(Participant.competition_id == competition_id)

        query = query.limit(1)
        result = await self.db.execute(query)
        participant = result.scalars().first()

        if not participant:
            raise HTTPException(status_code=404, detail="Not participating in active competition")

        return participant

    async def get_position(self, participant_id: UUID, code: str) -> Optional[Position]:
        """특정 코인 포지션 조회"""
        result = await self.db.execute(
            select(Position).where(
                Position.participant_id == participant_id,
                Position.code == code
            )
        )
        return result.scalar_one_or_none()

    async def get_positions(self, participant_id: UUID) -> list[Position]:
        """모든 포지션 조회"""
        result = await self.db.execute(
            select(Position).where(Position.participant_id == participant_id)
        )
        return list(result.scalars().all())

    async def upsert_position(
        self,
        participant_id: UUID,
        code: str,
        quantity: Decimal,
        price: Decimal
    ) -> None:
        """포지션 UPSERT (Race condition 방지)

        PostgreSQL ON CONFLICT를 사용하여 원자적으로 포지션 추가/업데이트
        DB 제약조건 'uq_position_participant_code' 활용
        """
        await self.db.execute(
            text("""
                INSERT INTO positions (id, participant_id, code, quantity, avg_buy_price, created_at, updated_at)
                VALUES (gen_random_uuid(), :participant_id, :code, :quantity, :avg_buy_price, NOW(), NOW())
                ON CONFLICT ON CONSTRAINT uq_position_participant_code DO UPDATE SET
                    quantity = positions.quantity + EXCLUDED.quantity,
                    avg_buy_price = CASE
                        WHEN positions.quantity + EXCLUDED.quantity > 0 THEN
                            (positions.quantity * positions.avg_buy_price + EXCLUDED.quantity * EXCLUDED.avg_buy_price)
                            / (positions.quantity + EXCLUDED.quantity)
                        ELSE positions.avg_buy_price
                    END,
                    updated_at = NOW()
            """),
            {
                "participant_id": str(participant_id),
                "code": code,
                "quantity": float(quantity),
                "avg_buy_price": float(price)
            }
        )

    async def cleanup_zero_positions(self, participant_id: UUID, code: str) -> int:
        """0 이하인 포지션 정리

        부동소수점 오차를 고려하여 0.0001 이하인 포지션도 삭제

        Returns:
            삭제된 포지션 수
        """
        result = await self.db.execute(
            delete(Position).where(
                Position.participant_id == participant_id,
                Position.code == code,
                Position.quantity <= Decimal("0.0001")  # 부동소수점 오차 허용
            )
        )
        return result.rowcount

    async def create_market_order(
        self,
        participant: Participant,
        code: str,
        side: str,
        quantity: Decimal,
        current_price: Decimal
    ) -> Order:
        """시장가 주문 생성 및 즉시 체결

        Race condition 방지를 위해 DB 레벨에서 잔고/포지션 검증 수행
        """
        # 1. 기본 가격 범위 검증
        if not validate_price(code, current_price):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid price for {code}: {current_price}. Price is outside reasonable range."
            )

        fee_rate = Decimal(str(settings.FEE_RATE))
        total_amount = current_price * quantity
        fee = total_amount * fee_rate

        if side == "buy":
            total_cost = total_amount + fee

            # 2. 잔고 검증 (1차 - 빠른 실패)
            if Decimal(str(participant.balance)) < total_cost:
                raise HTTPException(status_code=400, detail="Insufficient balance")

            # 3. DB 레벨에서 원자적 잔고 차감 (Race condition 방지)
            # balance >= total_cost 조건으로 업데이트, 조건 불만족 시 0행 업데이트
            result = await self.db.execute(
                update(Participant)
                .where(
                    Participant.id == participant.id,
                    Participant.balance >= total_cost  # 핵심: DB 레벨 잔고 검증
                )
                .values(balance=Participant.balance - total_cost)
            )

            if result.rowcount == 0:
                raise HTTPException(
                    status_code=400,
                    detail="Insufficient balance (concurrent request detected)"
                )

        else:  # sell
            position = await self.get_position(participant.id, code)

            # 2. 포지션 검증 (1차 - 빠른 실패)
            if not position or Decimal(str(position.quantity)) < quantity:
                raise HTTPException(status_code=400, detail="Insufficient position")

            # 3. DB 레벨에서 원자적 포지션 차감 (Race condition 방지)
            result = await self.db.execute(
                update(Position)
                .where(
                    Position.id == position.id,
                    Position.quantity >= quantity  # 핵심: DB 레벨 포지션 검증
                )
                .values(quantity=Position.quantity - quantity)
            )

            if result.rowcount == 0:
                raise HTTPException(
                    status_code=400,
                    detail="Insufficient position (concurrent request detected)"
                )

        # 주문 생성 (즉시 체결 상태)
        order = Order(
            participant_id=participant.id,
            code=code,
            side=side,
            order_type="market",
            price=None,
            quantity=quantity,
            filled_quantity=quantity,
            filled_price=current_price,
            fee=fee,
            status="filled",
            filled_at=datetime.utcnow()
        )
        self.db.add(order)
        await self.db.flush()

        # 잔고/포지션 업데이트 (매수 시 포지션 추가, 매도 시 잔고 추가)
        await self._update_balance_and_position_after_atomic(
            participant, code, side, quantity, current_price, fee
        )

        # 거래 내역 생성
        trade = Trade(
            order_id=order.id,
            participant_id=participant.id,
            code=code,
            side=side,
            price=current_price,
            quantity=quantity,
            total_amount=total_amount,
            fee=fee
        )
        self.db.add(trade)

        await self.db.commit()
        await self.db.refresh(order)

        return order

    async def create_limit_order(
        self,
        participant: Participant,
        code: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        current_price: Optional[Decimal] = None
    ) -> Order:
        """지정가 주문 생성

        즉시 체결 조건:
        - 매수: 지정가 >= 현재가 → 현재가로 즉시 체결
        - 매도: 지정가 <= 현재가 → 현재가로 즉시 체결

        Race condition 방지를 위해 DB 레벨에서 잔고/포지션 검증 수행
        """
        # 1. 기본 가격 범위 검증
        if not validate_price(code, price):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid price for {code}: {price}. Price is outside reasonable range."
            )

        # 2. 시장가 대비 가격 검증 (현재가가 있는 경우)
        if current_price is not None:
            if not validate_price_against_market(code, price, current_price):
                raise HTTPException(
                    status_code=400,
                    detail=f"Price {price} deviates too much from market price {current_price}. Max allowed: ±{MAX_PRICE_DEVIATION:.0%}"
                )

        # 3. 즉시 체결 조건 확인
        if current_price is not None:
            should_execute_immediately = False
            if side == "buy" and price >= current_price:
                # 매수 지정가 >= 현재가: 더 비싸게 사겠다 → 현재가로 즉시 체결
                should_execute_immediately = True
            elif side == "sell" and price <= current_price:
                # 매도 지정가 <= 현재가: 더 싸게 팔겠다 → 현재가로 즉시 체결
                should_execute_immediately = True

            if should_execute_immediately:
                # 시장가 주문처럼 즉시 체결 (현재가로)
                return await self.create_market_order(
                    participant=participant,
                    code=code,
                    side=side,
                    quantity=quantity,
                    current_price=current_price
                )

        fee_rate = Decimal(str(settings.FEE_RATE))
        total_amount = price * quantity
        fee = total_amount * fee_rate

        # 4. DB 레벨에서 원자적 잔고/포지션 선점 (Race condition 방지)
        if side == "buy":
            total_cost = total_amount + fee

            # 빠른 실패
            if Decimal(str(participant.balance)) < total_cost:
                raise HTTPException(status_code=400, detail="Insufficient balance")

            # DB 레벨 원자적 잔고 선점
            result = await self.db.execute(
                update(Participant)
                .where(
                    Participant.id == participant.id,
                    Participant.balance >= total_cost  # DB 레벨 검증
                )
                .values(balance=Participant.balance - total_cost)
            )

            if result.rowcount == 0:
                raise HTTPException(
                    status_code=400,
                    detail="Insufficient balance (concurrent request detected)"
                )

        else:  # sell
            position = await self.get_position(participant.id, code)

            if not position or Decimal(str(position.quantity)) < quantity:
                raise HTTPException(status_code=400, detail="Insufficient position")

            # DB 레벨 원자적 포지션 선점
            result = await self.db.execute(
                update(Position)
                .where(
                    Position.id == position.id,
                    Position.quantity >= quantity  # DB 레벨 검증
                )
                .values(quantity=Position.quantity - quantity)
            )

            if result.rowcount == 0:
                raise HTTPException(
                    status_code=400,
                    detail="Insufficient position (concurrent request detected)"
                )

        # 주문 생성 (대기 상태)
        order = Order(
            participant_id=participant.id,
            code=code,
            side=side,
            order_type="limit",
            price=price,
            quantity=quantity,
            status="pending"
        )
        self.db.add(order)

        await self.db.commit()
        await self.db.refresh(order)

        return order

    async def cancel_order(self, order: Order) -> Order:
        """주문 취소"""
        if order.status != "pending":
            raise HTTPException(status_code=400, detail="Only pending orders can be cancelled")

        if order.order_type != "limit":
            raise HTTPException(status_code=400, detail="Only limit orders can be cancelled")

        fee_rate = Decimal(str(settings.FEE_RATE))
        total_amount = Decimal(str(order.price)) * Decimal(str(order.quantity))
        fee = total_amount * fee_rate

        # 선점된 잔고/포지션 복구
        if order.side == "buy":
            total_cost = total_amount + fee
            await self.db.execute(
                update(Participant)
                .where(Participant.id == order.participant_id)
                .values(balance=Participant.balance + total_cost)
            )
        else:  # sell
            # 포지션 복구 시도
            result = await self.db.execute(
                update(Position)
                .where(
                    Position.participant_id == order.participant_id,
                    Position.code == order.code
                )
                .values(quantity=Position.quantity + order.quantity)
            )

            # 포지션 레코드가 없는 경우 (cleanup으로 삭제된 경우) 새로 생성
            if result.rowcount == 0:
                logger.warning(
                    f"Position not found during sell cancel. Creating new position. "
                    f"participant_id={order.participant_id}, code={order.code}, quantity={order.quantity}"
                )
                # UPSERT로 포지션 복구 (race condition 방지)
                await self.db.execute(
                    text("""
                        INSERT INTO positions (id, participant_id, code, quantity, avg_buy_price, created_at, updated_at)
                        VALUES (gen_random_uuid(), :participant_id, :code, :quantity, :avg_buy_price, NOW(), NOW())
                        ON CONFLICT ON CONSTRAINT uq_position_participant_code DO UPDATE SET
                            quantity = positions.quantity + EXCLUDED.quantity,
                            updated_at = NOW()
                    """),
                    {
                        "participant_id": str(order.participant_id),
                        "code": order.code,
                        "quantity": float(order.quantity),
                        "avg_buy_price": float(order.price)  # 정확한 값은 아니지만 복구 우선
                    }
                )

        # 주문 상태 업데이트
        order.status = "cancelled"
        order.cancelled_at = datetime.utcnow()

        await self.db.commit()
        await self.db.refresh(order)

        return order

    async def execute_limit_order(self, order: Order, execution_price: Decimal) -> Order:
        """지정가 주문 체결 실행 (매칭 엔진에서 호출)"""
        # 체결 가격 유효성 검증
        if not validate_price(order.code, execution_price):
            logger.warning(f"Skipping limit order execution due to invalid price: {order.code} @ {execution_price}")
            raise ValueError(f"Invalid execution price for {order.code}: {execution_price}")

        fee_rate = Decimal(str(settings.FEE_RATE))
        total_amount = execution_price * Decimal(str(order.quantity))
        fee = total_amount * fee_rate

        # 참가자 조회
        result = await self.db.execute(
            select(Participant).where(Participant.id == order.participant_id)
        )
        participant = result.scalar_one()

        # 지정가 주문은 이미 잔고/포지션이 선점되어 있음
        # 실제 체결 처리만 수행

        if order.side == "buy":
            # 매수: 코인 포지션 추가 (UPSERT 사용 - Race condition 방지)
            await self.upsert_position(
                participant.id,
                order.code,
                Decimal(str(order.quantity)),
                execution_price
            )

            # 지정가와 실제 체결가 차이만큼 잔고 조정
            price_diff = Decimal(str(order.price)) - execution_price
            if price_diff > 0:
                # 더 싼 가격에 체결됨 -> 차액 반환
                refund = price_diff * Decimal(str(order.quantity))
                await self.db.execute(
                    update(Participant)
                    .where(Participant.id == participant.id)
                    .values(balance=Participant.balance + refund)
                )

        else:  # sell
            # 매도: 체결 대금 입금
            receive_amount = total_amount - fee
            await self.db.execute(
                update(Participant)
                .where(Participant.id == participant.id)
                .values(balance=Participant.balance + receive_amount)
            )

            # 포지션 정리 (0 이하 또는 부동소수점 오차 범위 내)
            await self.cleanup_zero_positions(participant.id, order.code)

        # 주문 상태 업데이트
        order.status = "filled"
        order.filled_quantity = order.quantity
        order.filled_price = execution_price
        order.fee = fee
        order.filled_at = datetime.utcnow()

        # 거래 내역 생성
        trade = Trade(
            order_id=order.id,
            participant_id=participant.id,
            code=order.code,
            side=order.side,
            price=execution_price,
            quantity=order.quantity,
            total_amount=total_amount,
            fee=fee
        )
        self.db.add(trade)

        await self.db.commit()
        await self.db.refresh(order)

        return order

    async def _update_balance_and_position_after_atomic(
        self,
        participant: Participant,
        code: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal
    ):
        """원자적 차감 이후 나머지 업데이트 (시장가 주문용)

        create_market_order에서 이미 원자적으로:
        - 매수: 잔고 차감 완료
        - 매도: 포지션 차감 완료

        이 함수는 나머지 업데이트만 수행:
        - 매수: 포지션 추가 (UPSERT 사용)
        - 매도: 잔고 추가, 포지션 0이면 삭제
        """
        total_amount = price * quantity

        if side == "buy":
            # 잔고는 이미 차감됨, 포지션 UPSERT (Race condition 방지)
            await self.upsert_position(participant.id, code, quantity, price)

        else:  # sell
            # 포지션은 이미 차감됨, 잔고 추가 및 포지션 정리
            receive_amount = total_amount - fee
            await self.db.execute(
                update(Participant)
                .where(Participant.id == participant.id)
                .values(balance=Participant.balance + receive_amount)
            )

            # 포지션 정리 (0 이하 또는 부동소수점 오차 범위 내)
            await self.cleanup_zero_positions(participant.id, code)

    async def _update_balance_and_position(
        self,
        participant: Participant,
        code: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal
    ):
        """잔고 및 포지션 업데이트 (레거시 - 지정가 체결용)"""
        total_amount = price * quantity

        if side == "buy":
            # 잔고 차감
            total_cost = total_amount + fee
            await self.db.execute(
                update(Participant)
                .where(Participant.id == participant.id)
                .values(balance=Participant.balance - total_cost)
            )

            # 포지션 업데이트
            position = await self.get_position(participant.id, code)
            if position:
                # 평균 매수가 계산
                old_total = Decimal(str(position.quantity)) * Decimal(str(position.avg_buy_price))
                new_total = quantity * price
                new_quantity = Decimal(str(position.quantity)) + quantity
                new_avg_price = (old_total + new_total) / new_quantity

                await self.db.execute(
                    update(Position)
                    .where(Position.id == position.id)
                    .values(
                        quantity=new_quantity,
                        avg_buy_price=new_avg_price
                    )
                )
            else:
                position = Position(
                    participant_id=participant.id,
                    code=code,
                    quantity=quantity,
                    avg_buy_price=price
                )
                self.db.add(position)

        else:  # sell
            # 잔고 증가
            receive_amount = total_amount - fee
            await self.db.execute(
                update(Participant)
                .where(Participant.id == participant.id)
                .values(balance=Participant.balance + receive_amount)
            )

            # 포지션 차감
            position = await self.get_position(participant.id, code)
            new_quantity = Decimal(str(position.quantity)) - quantity

            if new_quantity <= 0:
                await self.db.execute(
                    delete(Position).where(Position.id == position.id)
                )
            else:
                await self.db.execute(
                    update(Position)
                    .where(Position.id == position.id)
                    .values(quantity=new_quantity)
                )
