"""지정가 주문 체결 엔진"""
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.order import Order
from services.order_service import OrderService


class MatchingEngine:
    """실시간 시세에 따른 지정가 주문 체결 엔진"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.order_service = OrderService(db)

    async def process_ticker(self, data: dict) -> int:
        """시세 데이터 수신 시 지정가 주문 체결 확인

        Args:
            data: Upbit 시세 데이터 (code, trade_price 포함)

        Returns:
            int: 체결된 주문 수
        """
        code = data.get("code")
        current_price = data.get("trade_price")

        if not code or not current_price:
            return 0

        current_price = Decimal(str(current_price))
        filled_count = 0

        # 매수 지정가 주문: 현재가 <= 지정가
        buy_orders = await self._get_pending_buy_orders(code, current_price)
        for order in buy_orders:
            try:
                await self.order_service.execute_limit_order(order, current_price)
                filled_count += 1
                print(f"  [체결] BUY {order.code} @ {current_price}")
            except Exception as e:
                print(f"  [체결 실패] {order.id}: {e}")

        # 매도 지정가 주문: 현재가 >= 지정가
        sell_orders = await self._get_pending_sell_orders(code, current_price)
        for order in sell_orders:
            try:
                await self.order_service.execute_limit_order(order, current_price)
                filled_count += 1
                print(f"  [체결] SELL {order.code} @ {current_price}")
            except Exception as e:
                print(f"  [체결 실패] {order.id}: {e}")

        return filled_count

    async def _get_pending_buy_orders(self, code: str, current_price: Decimal) -> list[Order]:
        """체결 가능한 매수 지정가 주문 조회

        조건: 현재가 <= 지정가 (더 싼 가격에 살 수 있음)
        """
        result = await self.db.execute(
            select(Order).where(
                Order.code == code,
                Order.status == "pending",
                Order.order_type == "limit",
                Order.side == "buy",
                Order.price >= current_price  # 지정가가 현재가보다 높거나 같음
            ).order_by(Order.created_at)  # 먼저 낸 주문 우선
        )
        return list(result.scalars().all())

    async def _get_pending_sell_orders(self, code: str, current_price: Decimal) -> list[Order]:
        """체결 가능한 매도 지정가 주문 조회

        조건: 현재가 >= 지정가 (더 비싼 가격에 팔 수 있음)
        """
        result = await self.db.execute(
            select(Order).where(
                Order.code == code,
                Order.status == "pending",
                Order.order_type == "limit",
                Order.side == "sell",
                Order.price <= current_price  # 지정가가 현재가보다 낮거나 같음
            ).order_by(Order.created_at)  # 먼저 낸 주문 우선
        )
        return list(result.scalars().all())


# 전역 인스턴스용 함수
async def process_ticker_for_matching(db: AsyncSession, data: dict) -> int:
    """시세 데이터로 매칭 엔진 실행 (외부 호출용)"""
    engine = MatchingEngine(db)
    return await engine.process_ticker(data)
