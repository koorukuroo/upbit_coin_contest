"""PostgreSQL 데이터베이스 연결 모듈"""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool
from config import settings

# 비동기 엔진 생성 (성능 최적화)
engine = create_async_engine(
    settings.POSTGRES_URL,
    echo=False,
    # 커넥션 풀 설정
    pool_size=20,              # 기본 풀 크기 증가
    max_overflow=30,           # 최대 추가 연결 수
    pool_timeout=30,           # 연결 대기 타임아웃 (초)
    pool_recycle=1800,         # 30분마다 연결 재활용 (stale 방지)
    pool_pre_ping=True,        # 연결 상태 확인 (끊어진 연결 자동 재연결)
    # asyncpg 성능 옵션
    connect_args={
        "server_settings": {
            "jit": "off",                    # JIT 비활성화 (짧은 쿼리에 유리)
            "statement_timeout": "30000",    # 30초 쿼리 타임아웃
        },
        "command_timeout": 30,
    },
)

# 세션 팩토리
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Base 클래스
Base = declarative_base()


async def get_db() -> AsyncSession:
    """FastAPI 의존성 주입용 DB 세션"""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """데이터베이스 초기화 (테이블 생성)"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
