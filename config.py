"""환경 설정 모듈"""
import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()


class Settings:
    """애플리케이션 설정"""

    # PostgreSQL
    POSTGRES_URL: str = os.getenv(
        "POSTGRES_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/trading"
    )

    # ClickHouse (기존)
    CLICKHOUSE_HOST: str = os.getenv("CLICKHOUSE_HOST", "localhost")
    CLICKHOUSE_PORT: int = int(os.getenv("CLICKHOUSE_PORT", "8123"))
    CLICKHOUSE_USER: str = os.getenv("CLICKHOUSE_USER", "default")
    CLICKHOUSE_PASSWORD: str = os.getenv("CLICKHOUSE_PASSWORD", "clickhousepw")
    CLICKHOUSE_DATABASE: str = os.getenv("CLICKHOUSE_DATABASE", "default")

    # Redis (ElastiCache)
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_PASSWORD: str = os.getenv("REDIS_PASSWORD", "")
    REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))
    REDIS_SSL: bool = os.getenv("REDIS_SSL", "false").lower() == "true"

    # Cache TTL (seconds)
    CACHE_TTL_CANDLES: int = int(os.getenv("CACHE_TTL_CANDLES", "5"))
    CACHE_TTL_TICKERS: int = int(os.getenv("CACHE_TTL_TICKERS", "1"))
    CACHE_TTL_LEADERBOARD: int = int(os.getenv("CACHE_TTL_LEADERBOARD", "10"))

    # Clerk 인증
    CLERK_SECRET_KEY: str = os.getenv("CLERK_SECRET_KEY", "")
    CLERK_PUBLISHABLE_KEY: str = os.getenv("CLERK_PUBLISHABLE_KEY", "")

    # 대회 설정
    FEE_RATE: float = float(os.getenv("FEE_RATE", "0.0005"))
    INITIAL_BALANCE: float = float(os.getenv("INITIAL_BALANCE", "1000000"))

    # 관리자 이메일 (쉼표로 구분하여 여러 명 지정 가능)
    ADMIN_EMAILS: list = [e.strip() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()]

    # 지원 코인 목록
    SUPPORTED_CODES: list = [
        'KRW-BTC', 'KRW-ETH', 'KRW-XRP', 'KRW-SOL', 'KRW-DOGE',
        'KRW-ADA', 'KRW-AVAX', 'KRW-DOT', 'KRW-LINK', 'KRW-MATIC'
    ]


settings = Settings()
