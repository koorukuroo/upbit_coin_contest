"""주문 모델"""
import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import Column, String, DateTime, Numeric, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    participant_id = Column(UUID(as_uuid=True), ForeignKey("participants.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(20), nullable=False)  # 코인 코드
    side = Column(String(10), nullable=False)  # buy, sell
    order_type = Column(String(10), nullable=False)  # market, limit
    price = Column(Numeric(20, 8), nullable=True)  # 지정가 (시장가는 NULL)
    quantity = Column(Numeric(20, 8), nullable=False)  # 주문 수량
    filled_quantity = Column(Numeric(20, 8), default=Decimal("0"))  # 체결된 수량
    filled_price = Column(Numeric(20, 8), nullable=True)  # 체결 평균 가격
    fee = Column(Numeric(20, 8), default=Decimal("0"))  # 수수료
    status = Column(String(20), default="pending")  # pending, filled, partially_filled, cancelled
    created_at = Column(DateTime, default=datetime.utcnow)
    filled_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)

    # 관계
    participant = relationship("Participant", back_populates="orders")
    trades = relationship("Trade", back_populates="order", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Order {self.side} {self.code} qty={self.quantity} status={self.status}>"

    @property
    def is_pending(self) -> bool:
        """주문이 대기 중인지 확인"""
        return self.status == "pending"

    @property
    def is_filled(self) -> bool:
        """주문이 완전 체결되었는지 확인"""
        return self.status == "filled"

    @property
    def remaining_quantity(self) -> Decimal:
        """미체결 수량"""
        return self.quantity - self.filled_quantity
