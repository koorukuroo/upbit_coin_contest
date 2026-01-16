#!/usr/bin/env python3
"""
ClickHouse 데이터 마이그레이션 스크립트
원본 서버에서 새 서버로 데이터를 중복 없이 마이그레이션합니다.
"""
import clickhouse_connect

# 원본 서버 설정
SRC_HOST = "16.176.20.39"
SRC_PORT = 9000  # Native Protocol
SRC_USER = "default"
SRC_PASSWORD = "clickhouse:clickhouse"

# 새 서버 설정 (로컬)
DST_HOST = "localhost"
DST_PORT = 8123
DST_USER = "default"
DST_PASSWORD = "clickhousepw"
DST_DATABASE = "default"


def migrate():
    print("=" * 60)
    print("ClickHouse 데이터 마이그레이션")
    print("=" * 60)
    print(f"원본: {SRC_HOST}:{SRC_PORT}")
    print(f"대상: {DST_HOST}:{DST_PORT}")
    print("=" * 60)

    # 새 서버 연결
    client = clickhouse_connect.get_client(
        host=DST_HOST,
        port=DST_PORT,
        username=DST_USER,
        password=DST_PASSWORD,
        database=DST_DATABASE
    )
    print("✅ 새 서버 연결 성공")

    # 1. 현재 데이터 수 확인
    result = client.query("SELECT count() FROM upbit_ticker")
    current_count = result.result_rows[0][0]
    print(f"📊 현재 데이터 수: {current_count:,}")

    # 2. 기존 테이블 백업
    print("\n🔄 1단계: 기존 테이블 백업...")
    try:
        client.command("DROP TABLE IF EXISTS upbit_ticker_backup")
        client.command("RENAME TABLE upbit_ticker TO upbit_ticker_backup")
        print("   ✅ 백업 완료: upbit_ticker → upbit_ticker_backup")
    except Exception as e:
        print(f"   ⚠️ 백업 스킵 (테이블 없음): {e}")

    # 3. ReplacingMergeTree로 새 테이블 생성
    print("\n🔄 2단계: ReplacingMergeTree 테이블 생성...")
    client.command("""
        CREATE TABLE IF NOT EXISTS upbit_ticker (
            timestamp DateTime64(3),
            code String,
            opening_price Float64,
            high_price Float64,
            low_price Float64,
            trade_price Float64,
            prev_closing_price Float64,
            change String,
            change_price Float64,
            signed_change_price Float64,
            change_rate Float64,
            signed_change_rate Float64,
            trade_volume Float64,
            acc_trade_volume Float64,
            acc_trade_volume_24h Float64,
            acc_trade_price Float64,
            acc_trade_price_24h Float64,
            trade_timestamp Int64,
            ask_bid String,
            acc_ask_volume Float64,
            acc_bid_volume Float64
        ) ENGINE = ReplacingMergeTree()
        ORDER BY (code, timestamp)
    """)
    print("   ✅ 테이블 생성 완료 (ReplacingMergeTree)")

    # 4. 백업 데이터 복원
    print("\n🔄 3단계: 백업 데이터 복원...")
    try:
        client.command("INSERT INTO upbit_ticker SELECT * FROM upbit_ticker_backup")
        result = client.query("SELECT count() FROM upbit_ticker")
        restored_count = result.result_rows[0][0]
        print(f"   ✅ 복원 완료: {restored_count:,} rows")
    except Exception as e:
        print(f"   ⚠️ 복원 스킵 (백업 없음): {e}")

    # 5. 원본 서버에서 데이터 가져오기
    print(f"\n🔄 4단계: 원본 서버({SRC_HOST})에서 데이터 가져오기...")
    print("   ⏳ 시간이 걸릴 수 있습니다...")

    try:
        client.command(f"""
            INSERT INTO upbit_ticker
            SELECT * FROM remote(
                '{SRC_HOST}:{SRC_PORT}',
                'default',
                'upbit_ticker',
                '{SRC_USER}',
                '{SRC_PASSWORD}'
            )
        """)
        result = client.query("SELECT count() FROM upbit_ticker")
        after_import = result.result_rows[0][0]
        print(f"   ✅ 가져오기 완료: {after_import:,} rows (중복 포함)")
    except Exception as e:
        print(f"   ❌ 원본 서버 연결 실패: {e}")
        print("   💡 SG에서 9000 포트가 열려있는지 확인하세요")
        return

    # 6. 중복 제거
    print("\n🔄 5단계: 중복 제거 (OPTIMIZE)...")
    print("   ⏳ 시간이 걸릴 수 있습니다...")
    client.command("OPTIMIZE TABLE upbit_ticker FINAL")
    result = client.query("SELECT count() FROM upbit_ticker")
    final_count = result.result_rows[0][0]
    print(f"   ✅ 중복 제거 완료: {final_count:,} rows")

    # 7. 결과 확인
    print("\n🔄 6단계: 결과 확인...")
    result = client.query("""
        SELECT
            min(timestamp) as first_time,
            max(timestamp) as last_time,
            count() as total_rows,
            count(DISTINCT code) as unique_codes
        FROM upbit_ticker
    """)
    row = result.result_rows[0]
    print(f"   📅 기간: {row[0]} ~ {row[1]}")
    print(f"   📊 총 데이터: {row[2]:,} rows")
    print(f"   🪙 코드 수: {row[3]}")

    # 8. 백업 테이블 삭제
    print("\n🔄 7단계: 백업 테이블 정리...")
    try:
        client.command("DROP TABLE IF EXISTS upbit_ticker_backup")
        print("   ✅ 백업 테이블 삭제 완료")
    except:
        pass

    print("\n" + "=" * 60)
    print("🎉 마이그레이션 완료!")
    print("=" * 60)


if __name__ == "__main__":
    migrate()
