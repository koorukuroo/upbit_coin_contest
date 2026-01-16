import sys
import clickhouse_connect

CH_HOST = "localhost"
CH_PORT = 8123
CH_USER = "default"
CH_PASSWORD = "clickhouse:clickhouse"
CH_DATABASE = "default"

client = clickhouse_connect.get_client(
    host=CH_HOST,
    port=CH_PORT,
    username=CH_USER,
    password=CH_PASSWORD,
    database=CH_DATABASE
)

def count():
    """전체 row 수"""
    result = client.query("SELECT count() FROM upbit_ticker")
    print(f"Total rows: {result.result_rows[0][0]}")

def recent(limit=10):
    """최근 데이터"""
    result = client.query(f"""
        SELECT timestamp, code, trade_price
        FROM upbit_ticker
        ORDER BY timestamp DESC
        LIMIT {limit}
    """)
    print(f"{'timestamp':<26} {'code':<15} {'price':>15}")
    print("-" * 60)
    for row in result.result_rows:
        print(f"{str(row[0]):<26} {row[1]:<15} {row[2]:>15,.2f}")

def by_code(code, limit=10):
    """특정 코드 조회"""
    result = client.query(f"""
        SELECT timestamp, code, trade_price
        FROM upbit_ticker
        WHERE code = '{code}'
        ORDER BY timestamp DESC
        LIMIT {limit}
    """)
    print(f"{'timestamp':<26} {'code':<15} {'price':>15}")
    print("-" * 60)
    for row in result.result_rows:
        print(f"{str(row[0]):<26} {row[1]:<15} {row[2]:>15,.2f}")

def full(limit=5):
    """전체 컬럼 조회"""
    result = client.query(f"""
        SELECT *
        FROM upbit_ticker
        ORDER BY timestamp DESC
        LIMIT {limit}
    """)
    cols = result.column_names
    for i, row in enumerate(result.result_rows):
        print(f"=== Row {i+1} ===")
        for col, val in zip(cols, row):
            print(f"  {col}: {val}")
        print()

def stats():
    """코드별 통계"""
    result = client.query("""
        SELECT
            code,
            count() as cnt,
            min(trade_price) as min_price,
            max(trade_price) as max_price,
            avg(trade_price) as avg_price
        FROM upbit_ticker
        GROUP BY code
        ORDER BY cnt DESC
        LIMIT 20
    """)
    print(f"{'code':<15} {'count':>10} {'min':>15} {'max':>15} {'avg':>15}")
    print("-" * 75)
    for row in result.result_rows:
        print(f"{row[0]:<15} {row[1]:>10} {row[2]:>15,.2f} {row[3]:>15,.2f} {row[4]:>15,.2f}")

def help():
    print("""
Usage: python query.py <command> [args]

Commands:
  count              - 전체 row 수
  recent [limit]     - 최근 데이터 (기본 10개)
  code <code> [limit] - 특정 코드 조회 (예: KRW-BTC)
  stats              - 코드별 통계
  full [limit]       - 전체 컬럼 조회 (기본 5개)
""")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        help()
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "count":
        count()
    elif cmd == "recent":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        recent(limit)
    elif cmd == "code":
        if len(sys.argv) < 3:
            print("Usage: python query.py code <code> [limit]")
            sys.exit(1)
        code = sys.argv[2]
        limit = int(sys.argv[3]) if len(sys.argv) > 3 else 10
        by_code(code, limit)
    elif cmd == "stats":
        stats()
    elif cmd == "full":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        full(limit)
    else:
        help()
