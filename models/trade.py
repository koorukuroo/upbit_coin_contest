"""거래 내역 모델"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Numeric, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database import Base


class Trade(Base):
    __tablename__ = "trades"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    participant_id = Column(UUID(as_uuid=True), ForeignKey("participants.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)  # buy, sell
    price = Column(Numeric(20, 8), nullable=False)  # 체결 가격
    quantity = Column(Numeric(20, 8), nullable=False)  # 체결 수량
    total_amount = Column(Numeric(20, 8), nullable=False)  # 총 금액
    fee = Column(Numeric(20, 8), nullable=False)  # 수수료
    created_at = Column(DateTime, default=datetime.utcnow)

    # 관계
    order = relationship("Order", back_populates="trades")
    participant = relationship("Participant", back_populates="trades")

    def __repr__(self):
        return f"<Trade {self.side} {self.code} @ {self.price}>"
