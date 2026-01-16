"""대회 모델"""
import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import Column, String, Text, DateTime, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database import Base


class Competition(Base):
    __tablename__ = "competitions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    initial_balance = Column(Numeric(20, 8), nullable=False, default=Decimal("1000000"))
    fee_rate = Column(Numeric(10, 8), nullable=False, default=Decimal("0.0005"))
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    status = Column(String(20), default="pending")  # pending, active, ended
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 관계
    participants = relationship("Participant", back_populates="competition", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Competition {self.name}>"

    @property
    def is_active(self) -> bool:
        """대회가 진행 중인지 확인"""
        now = datetime.utcnow()
        return self.status == "active" and self.start_time <= now <= self.end_time
