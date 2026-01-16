"""포지션(보유 코인) 모델"""
import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import Column, String, DateTime, Numeric, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database import Base


class Position(Base):
    __tablename__ = "positions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    participant_id = Column(UUID(as_uuid=True), ForeignKey("participants.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(20), nullable=False)  # 코인 코드 (예: KRW-BTC)
    quantity = Column(Numeric(20, 8), nullable=False)  # 보유 수량
    avg_buy_price = Column(Numeric(20, 8), nullable=False)  # 평균 매수가
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 유니크 제약
    __table_args__ = (
        UniqueConstraint('participant_id', 'code', name='uq_position_participant_code'),
    )

    # 관계
    participant = relationship("Participant", back_populates="positions")

    def __repr__(self):
        return f"<Position {self.code} qty={self.quantity}>"

    @property
    def total_value(self) -> Decimal:
        """총 매수 금액"""
        return self.quantity * self.avg_buy_price
