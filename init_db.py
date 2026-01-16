"""데이터베이스 초기화 스크립트"""
import asyncio
import asyncpg
from pathlib import Path

# RDS 연결 정보
DB_HOST = "database-1.cjike4imesf1.ap-northeast-2.rds.amazonaws.com"
DB_PORT = 5432
DB_USER = "postgres"
DB_PASSWORD = "asjdfhseahj2"
DB_NAME = "trading"


async def create_database():
    """trading 데이터베이스 생성"""
    print("1. Connecting to PostgreSQL...")

    # postgres 기본 DB에 연결
    conn = await asyncpg.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database="postgres"
    )

    try:
        # trading DB 존재 여부 확인
        result = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", DB_NAME
        )

        if result:
            print(f"   Database '{DB_NAME}' already exists")
        else:
            # DB 생성
            await conn.execute(f'CREATE DATABASE {DB_NAME}')
            print(f"   Database '{DB_NAME}' created")

    finally:
        await conn.close()


async def apply_schema():
    """스키마 적용"""
    print("2. Applying schema...")

    # trading DB에 연결
    conn = await asyncpg.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )

    try:
        # SQL 파일 읽기
        sql_path = Path(__file__).parent / "migrations" / "001_initial.sql"
        sql = sql_path.read_text()

        # 실행
        await conn.execute(sql)
        print("   Schema applied successfully")

    except asyncpg.exceptions.DuplicateTableError:
        print("   Tables already exist (skipping)")
    except Exception as e:
        print(f"   Schema error: {e}")
        # 개별 테이블이 이미 있을 수 있으므로 무시
    finally:
        await conn.close()


async def create_admin_user():
    """초기 관리자 계정 생성 (선택적)"""
    print("3. Creating admin user (optional)...")

    conn = await asyncpg.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )

    try:
        # 관리자 계정이 있는지 확인
        result = await conn.fetchval(
            "SELECT 1 FROM users WHERE is_admin = TRUE LIMIT 1"
        )

        if result:
            print("   Admin user already exists")
        else:
            # 테스트용 관리자 계정 생성 (Clerk 연동 전용)
            await conn.execute("""
                INSERT INTO users (clerk_user_id, email, username, is_admin)
                VALUES ('admin_test', 'admin@test.com', 'Admin', TRUE)
                ON CONFLICT (clerk_user_id) DO NOTHING
            """)
            print("   Test admin user created (clerk_user_id: admin_test)")

    except Exception as e:
        print(f"   Error: {e}")
    finally:
        await conn.close()


async def create_sample_competition():
    """샘플 대회 생성"""
    print("4. Creating sample competition...")

    conn = await asyncpg.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )

    try:
        # 활성 대회가 있는지 확인
        result = await conn.fetchval(
            "SELECT 1 FROM competitions WHERE status = 'active' LIMIT 1"
        )

        if result:
            print("   Active competition already exists")
        else:
            # 샘플 대회 생성
            await conn.execute("""
                INSERT INTO competitions (name, description, initial_balance, fee_rate, start_time, end_time, status)
                VALUES (
                    '제1회 모의 투자 대회',
                    '실시간 Upbit 시세로 진행되는 모의 투자 대회입니다. 100만원으로 시작해서 수익률을 겨뤄보세요!',
                    1000000,
                    0.0005,
                    NOW(),
                    NOW() + INTERVAL '7 days',
                    'active'
                )
            """)
            print("   Sample competition created (7 days, active)")

    except Exception as e:
        print(f"   Error: {e}")
    finally:
        await conn.close()


async def main():
    print("=" * 50)
    print("Database Initialization")
    print("=" * 50)

    await create_database()
    await apply_schema()
    await create_admin_user()
    await create_sample_competition()

    print("=" * 50)
    print("Done!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
