"""참가자 모델"""
import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import Column, DateTime, Numeric, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database import Base


class Participant(Base):
    __tablename__ = "participants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    competition_id = Column(UUID(as_uuid=True), ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    balance = Column(Numeric(20, 8), nullable=False)  # KRW 잔고
    joined_at = Column(DateTime, default=datetime.utcnow)

    # 유니크 제약
    __table_args__ = (
        UniqueConstraint('competition_id', 'user_id', name='uq_participant_competition_user'),
    )

    # 관계
    competition = relationship("Competition", back_populates="participants")
    user = relationship("User", back_populates="participants")
    positions = relationship("Position", back_populates="participant", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="participant", cascade="all, delete-orphan")
    trades = relationship("Trade", back_populates="participant", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Participant user={self.user_id} balance={self.balance}>"
