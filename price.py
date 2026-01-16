import json
import time
import uuid
import threading
from datetime import datetime
import websocket
import clickhouse_connect

WS_URL = "wss://api.upbit.com/websocket/v1"
CH_HOST = "localhost"
CH_PORT = 8123
CH_USER = "default"
CH_PASSWORD = "clickhousepw"
CH_DATABASE = "default"

# ClickHouse 클라이언트 (전역)
ch_client = None

# 배치 버퍼
buffer = []
buffer_lock = threading.Lock()
BATCH_SIZE = 100  # 100개 모이면 저장
FLUSH_INTERVAL = 1.0  # 또는 1초마다 저장

# 통계
stats = {"total": 0, "last_report": 0}
stats_lock = threading.Lock()
STATS_INTERVAL = 10  # 10초마다 통계 출력

def init_clickhouse():
    """ClickHouse 연결 및 테이블 생성"""
    global ch_client
    ch_client = clickhouse_connect.get_client(
        host=CH_HOST,
        port=CH_PORT,
        username=CH_USER,
        password=CH_PASSWORD,
        database=CH_DATABASE
    )

    # 테이블 생성 (없으면)
    ch_client.command("""
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
        ) ENGINE = MergeTree()
        ORDER BY (code, timestamp)
    """)
    print("✅ ClickHouse connected, table ready")

def flush_buffer():
    """버퍼의 데이터를 ClickHouse에 저장"""
    global buffer
    with buffer_lock:
        if not buffer:
            return
        rows = buffer.copy()
        buffer = []

    try:
        ch_client.insert("upbit_ticker", rows)
        with stats_lock:
            stats["total"] += len(rows)
    except Exception as e:
        print(f"❌ ClickHouse insert error: {e}")

def flush_thread():
    """주기적으로 버퍼를 flush하는 스레드"""
    while not stop_event.is_set():
        time.sleep(FLUSH_INTERVAL)
        flush_buffer()

def stats_thread():
    """주기적으로 통계를 출력하는 스레드"""
    start_time = time.time()
    while not stop_event.is_set():
        time.sleep(STATS_INTERVAL)
        with stats_lock:
            total = stats["total"]
            new_rows = total - stats["last_report"]
            stats["last_report"] = total
        elapsed = time.time() - start_time
        rate = new_rows / STATS_INTERVAL
        print(f"📊 Total: {total:,} rows | +{new_rows} ({rate:.1f}/sec) | Uptime: {int(elapsed)}s")

CODES = ['BTC-BERA', 'BTC-FIL', 'BTC-SIGN', 'BTC-VIRTUAL', 'BTC-BAT', 'KRW-WAXP', 'USDT-PEPE', 'BTC-BAR', 'USDT-WCT', 'KRW-CARV', 'KRW-LSK', 'USDT-DOGE', 'KRW-0G', 'USDT-AXL', 'USDT-YGG', 'BTC-SCR', 'USDT-JASMY', 'BTC-WLD', 'BTC-VANA', 'BTC-LWA', 'BTC-DGB', 'USDT-BONK', 'BTC-BCH', 'BTC-JASMY', 'KRW-BORA', 'KRW-PUNDIX', 'BTC-ORBS', 'USDT-WAL', 'KRW-USD1', 'USDT-WLFI', 'KRW-BAT', 'USDT-ZK', 'USDT-NOM', 'KRW-HUNT', 'KRW-PENGU', 'KRW-FIL', 'BTC-ANIME', 'BTC-ORCA', 'KRW-BEAM', 'BTC-SOON', 'BTC-LRC', 'KRW-DOOD', 'BTC-TOKAMAK', 'BTC-SOPH', 'BTC-STRAX', 'KRW-WAVES', 'KRW-USDC', 'KRW-MOVE', 'KRW-TREE', 'BTC-GLMR', 'KRW-AERGO', 'KRW-WET', 'KRW-USDT', 'BTC-LSK', 'USDT-RENDER', 'BTC-SOMI', 'USDT-RESOLV', 'KRW-2Z', 'BTC-STEEM', 'USDT-LPT', 'KRW-BOUNTY', 'KRW-KAITO', 'USDT-WET', 'KRW-LPT', 'BTC-PROVE', 'BTC-DEEP', 'BTC-WET', 'USDT-ARPA', 'BTC-INIT', 'BTC-LPT', 'BTC-BREV', 'BTC-POLYX', 'KRW-BLAST', 'USDT-ANIME', 'USDT-USDC', 'USDT-TREE', 'BTC-BIO', 'USDT-WLD', 'BTC-DRIFT', 'USDT-FLUID', 'BTC-W', 'USDT-SCR', 'BTC-T', 'USDT-BAT', 'USDT-DOOD', 'BTC-SKY', 'KRW-DKA', 'BTC-A', 'BTC-G', 'BTC-DNT', 'BTC-BABY', 'USDT-BEAM', 'BTC-FORT', 'KRW-ANKR', 'KRW-ALGO', 'USDT-FIL', 'BTC-MIRA', 'BTC-HOLO', 'KRW-SHIB', 'BTC-ENSO', 'KRW-UNI', 'KRW-BIO', 'BTC-SYRUP', 'USDT-HUMA', 'BTC-OAS', 'KRW-WLFI', 'KRW-TOKAMAK', 'BTC-UNI', 'USDT-USD1', 'USDT-OBSR', 'KRW-CYBER', 'BTC-JUV', 'KRW-DOGE', 'KRW-WLD', 'KRW-PEPE', 'KRW-HBAR', 'KRW-BCH', 'BTC-BFC', 'USDT-CARV', 'KRW-NEWT', 'KRW-SEI', 'USDT-JUP', 'BTC-ZORA', 'BTC-MINA', 'BTC-KITE', 'KRW-BONK', 'KRW-JST', 'KRW-AAVE', 'KRW-JTO', 'BTC-DKA', 'USDT-BIGTIME', 'BTC-HAEDAL', 'BTC-JST', 'USDT-JTO', 'BTC-SEI', 'KRW-JUP', 'USDT-NEWT', 'BTC-JTO', 'USDT-TOSHI', 'USDT-BCH', 'USDT-DGB', 'BTC-JUP', 'USDT-LWA', 'KRW-FLOW', 'KRW-ALT', 'BTC-BEAM', 'KRW-LAYER', 'USDT-TUSD', 'BTC-STG', 'KRW-TRX', 'KRW-POWR', 'USDT-ORDER', 'KRW-ATOM', 'USDT-AVNT', 'BTC-USDC', 'BTC-MOVE', 'BTC-TREE', 'BTC-BOUNTY', 'BTC-STX', 'KRW-ARKM', 'USDT-BIO', 'BTC-USDP', 'BTC-USDT', 'BTC-USDS', 'BTC-BSV', 'KRW-CRO', 'BTC-SUI', 'KRW-NXPC', 'BTC-PUNDIX', 'KRW-A', 'BTC-MED', 'KRW-TRUMP', 'BTC-OBSR', 'KRW-F', 'KRW-G', 'USDT-UNI', 'BTC-USD1', 'BTC-MEW', 'USDT-OAS', 'BTC-HUMA', 'KRW-CELO', 'BTC-PROM', 'KRW-AERO', 'KRW-CTC', 'BTC-HUNT', 'BTC-PENGU', 'KRW-ANIME', 'KRW-APT', 'BTC-AUCTION', 'KRW-MOCA', 'KRW-API3', 'BTC-LINEA', 'USDT-SPK', 'BTC-WAXP', 'BTC-MOODENG', 'KRW-AHT', 'BTC-OGN', 'USDT-NEAR', 'BTC-SOL', 'USDT-BNT', 'BTC-HYPER', 'BTC-CARV', 'KRW-EGLD', 'USDT-AGLD', 'USDT-HYPER', 'BTC-SPK', 'BTC-BNT', 'KRW-ERA', 'USDT-SOL', 'USDT-SWELL', 'USDT-MOODENG', 'BTC-BORA', 'KRW-FF', 'BTC-DOT', 'KRW-PLUME', 'BTC-CPOOL', 'KRW-NEO', 'KRW-ETC', 'KRW-IOTA', 'KRW-IOST', 'KRW-AKT', 'KRW-COW', 'BTC-SNX', 'BTC-SNT', 'KRW-VIRTUAL', 'USDT-SUPER', 'KRW-ETH', 'BTC-PENDLE', 'BTC-MON', 'KRW-IQ', 'USDT-EGLD', 'KRW-IP', 'BTC-DOGE', 'KRW-NEAR', 'KRW-RVN', 'BTC-ZIL', 'KRW-AGLD', 'KRW-ID', 'KRW-IN', 'BTC-VAL', 'USDT-DRIFT', 'USDT-2Z', 'BTC-WAVES', 'BTC-NEWT', 'KRW-NOM', 'BTC-AAVE', 'BTC-0G', 'KRW-WAL', 'KRW-PENDLE', 'USDT-SONIC', 'USDT-SHELL', 'KRW-BLUR', 'BTC-MMT', 'KRW-AWE', 'USDT-ARKM', 'USDT-0G', 'BTC-GAS', 'USDT-MEW', 'USDT-PUFFER', 'KRW-THETA', 'USDT-AERO', 'KRW-AXL', 'BTC-WLFI', 'KRW-HP', 'USDT-API3', 'BTC-MNT', 'KRW-SAND', 'KRW-WCT', 'BTC-CTSI', 'BTC-MOC', 'USDT-MOCA', 'KRW-YGG', 'KRW-AXS', 'KRW-ARDR', 'BTC-IOTX', 'USDT-TAIKO', 'KRW-AQT', 'KRW-ME', 'USDT-CPOOL', 'KRW-TRUST', 'BTC-2Z', 'KRW-SONIC', 'USDT-NXPC', 'BTC-MLK', 'BTC-ALGO', 'BTC-ANKR', 'KRW-ARB', 'BTC-SXP', 'KRW-POL', 'KRW-CVC', 'KRW-T', 'KRW-W', 'KRW-ARK', 'KRW-AVNT', 'BTC-SUN', 'BTC-ZBT', 'KRW-LA', 'KRW-HYPER', 'BTC-LAYER', 'BTC-ARPA', 'KRW-ATH', 'USDT-SUN', 'USDT-ZBT', 'USDT-BTC', 'USDT-LINEA', 'USDT-TRUST', 'BTC-IOST', 'KRW-TAIKO', 'BTC-TRUMP', 'BTC-RENDER', 'BTC-RAD', 'KRW-AVAX', 'USDT-ONDO', 'USDT-PLUME', 'KRW-XAUT', 'KRW-CPOOL', 'BTC-EGLD', 'BTC-GO', 'BTC-PLUME', 'BTC-INTER', 'USDT-MON', 'BTC-GLM', 'KRW-IMX', 'BTC-RAY', 'BTC-ZRO', 'USDT-VIRTUAL', 'USDT-TRUMP', 'KRW-SC', 'USDT-BARD', 'KRW-INJ', 'KRW-MVL', 'USDT-MNT', 'BTC-ZRX', 'BTC-HP', 'BTC-IO', 'BTC-IP', 'KRW-HIVE', 'BTC-IN', 'BTC-IMX', 'BTC-CITY', 'USDT-PUMP', 'BTC-ID', 'USDT-LAYER', 'KRW-CBK', 'KRW-OM', 'BTC-AERO', 'BTC-CELO', 'BTC-INJ', 'USDT-MMT', 'USDT-GAS', 'KRW-XLM', 'KRW-OP', 'BTC-MVL', 'BTC-IQ', 'BTC-CBK', 'USDT-W', 'KRW-SAFE', 'KRW-GLM', 'BTC-XLM', 'KRW-SUPER', 'BTC-CYBER', 'BTC-MOCA', 'BTC-API3', 'BTC-RESOLV', 'KRW-LINEA', 'USDT-OXT', 'BTC-1INCH', 'KRW-KERNEL', 'BTC-FLOW', 'USDT-HAEDAL', 'KRW-POKT', 'USDT-ETHFI', 'BTC-LA', 'BTC-MTL', 'BTC-VET', 'BTC-POWR', 'BTC-ATOM', 'BTC-ARKM', 'KRW-ZKC', 'BTC-SONIC', 'BTC-OXT', 'USDT-ASTR', 'USDT-OPEN', 'KRW-KNC', 'BTC-NXPC', 'KRW-ZKP', 'KRW-AUCTION', 'KRW-ORDER', 'BTC-ME', 'BTC-ZKC', 'KRW-DRIFT', 'BTC-ZKP', 'BTC-SHELL', 'USDT-ZKP', 'KRW-FCT2', 'USDT-ZKC', 'USDT-MET2', 'USDT-SAHARA', 'KRW-MTL', 'KRW-VET', 'BTC-TAIKO', 'BTC-SPURS', 'USDT-CYBER', 'KRW-QTUM', 'KRW-TT', 'KRW-LINK', 'KRW-XRP', 'KRW-CHZ', 'KRW-ASTR', 'USDT-POKT', 'BTC-GTC', 'USDT-RAY', 'KRW-ZK', 'BTC-NAP', 'USDT-SAFE', 'USDT-RAD', 'KRW-STORJ', 'BTC-AHT', 'KRW-ENA', 'KRW-MANA', 'KRW-OPEN', 'KRW-GRS', 'KRW-PYTH', 'BTC-AVNT', 'USDT-XLM', 'BTC-TRUST', 'USDT-INJ', 'BTC-SAND', 'KRW-ENS', 'KRW-GRT', 'KRW-PUMP', 'BTC-AFC', 'BTC-ENA', 'BTC-BLUR', 'KRW-XTZ', 'BTC-TUSD', 'KRW-CKB', 'BTC-ENJ', 'USDT-B3', 'BTC-GRT', 'BTC-GRS', 'BTC-ENS', 'BTC-XTZ', 'KRW-KAVA', 'BTC-CKB', 'BTC-ARDR', 'BTC-TIA', 'KRW-TOSHI', 'KRW-BARD', 'KRW-ZRO', 'BTC-ACM', 'BTC-REI', 'BTC-KAITO', 'BTC-RED', 'KRW-RAY', 'BTC-ACS', 'KRW-ONDO', 'BTC-NEAR', 'USDT-ADA', 'BTC-ADA', 'BTC-ELF', 'KRW-ZRX', 'USDT-GO', 'BTC-AGLD', 'USDT-F', 'BTC-CHR', 'USDT-TIA', 'BTC-KERNEL', 'USDT-ACS', 'USDT-RED', 'KRW-GMT', 'BTC-CHZ', 'BTC-BIGTIME', 'BTC-ETHFI', 'BTC-XRP', 'KRW-TFUEL', 'USDT-XAUT', 'USDT-XPL', 'BTC-QTUM', 'BTC-GMT', 'KRW-XPL', 'BTC-AUDIO', 'KRW-MASK', 'BTC-FCT2', 'USDT-ZETA', 'KRW-COMP', 'KRW-ZETA', 'KRW-RED', 'BTC-XPL', 'KRW-TIA', 'USDT-FF', 'USDT-ZRX', 'KRW-ADA', 'KRW-ELF', 'USDT-ZRO', 'BTC-LINK', 'USDT-AHT', 'KRW-STEEM', 'BTC-APE', 'USDT-EPT', 'BTC-ORDER', 'BTC-CTC', 'BTC-POKT', 'BTC-APT', 'KRW-SOPH', 'KRW-MED', 'USDT-LA', 'KRW-1INCH', 'BTC-PUFFER', 'USDT-HOLO', 'USDT-MIRA', 'USDT-FORT', 'USDT-ENSO', 'BTC-AQT', 'KRW-MEW', 'BTC-SWELL', 'USDT-CKB', 'BTC-YB', 'KRW-ORBS', 'BTC-HIVE', 'USDT-KITE', 'BTC-SAFE', 'BTC-ZK', 'BTC-CRV', 'BTC-CRO', 'USDT-IP', 'USDT-FLOCK', 'USDT-IN', 'USDT-IO', 'USDT-ENA', 'KRW-RENDER', 'USDT-KERNEL', 'KRW-STG', 'KRW-ORCA', 'BTC-SUPER', 'USDT-XRP', 'USDT-ZORA', 'KRW-BERA', 'BTC-AKT', 'KRW-SIGN', 'BTC-COW', 'BTC-ETC', 'USDT-ALT', 'BTC-AVAX', 'USDT-BLAST', 'USDT-OP', 'BTC-XAUT', 'BTC-ETH', 'BTC-NEO', 'USDT-OM', 'USDT-PENGU', 'USDT-ETC', 'USDT-ETH', 'USDT-KAITO', 'USDT-NEO', 'USDT-COW', 'BTC-ALT', 'KRW-VANA', 'USDT-VTHO', 'KRW-DOT', 'USDT-AKT', 'BTC-EUL', 'BTC-TRX', 'BTC-FLOCK', 'KRW-MET2', 'KRW-MBL', 'BTC-ERA', 'BTC-MASK', 'BTC-GAME2', 'KRW-FLUID', 'USDT-MOVE', 'USDT-ME', 'BTC-NCT', 'USDT-NCT', 'KRW-BIGTIME', 'USDT-ERA', 'KRW-SNT', 'BTC-RLC', 'BTC-ZETA', 'KRW-SOL', 'KRW-QKC', 'BTC-COMP', 'KRW-META', 'BTC-BARD', 'USDT-VANA', 'USDT-SC', 'BTC-OP', 'BTC-OM', 'BTC-AXL', 'BTC-FLUID', 'KRW-SAHARA', 'BTC-ONDO', 'KRW-MLK', 'KRW-SXP', 'KRW-VTHO', 'BTC-AXS', 'BTC-YGG', 'USDT-SIGN', 'KRW-KITE', 'KRW-MINA', 'BTC-WCT', 'KRW-MMT', 'KRW-ZORA', 'USDT-BERA', 'KRW-GAS', 'BTC-NOM', 'KRW-MNT', 'KRW-MOC', 'USDT-SOPH', 'KRW-MOODENG', 'BTC-WAL', 'KRW-XEC', 'BTC-AWE', 'USDT-ORCA', 'BTC-SAHARA', 'KRW-MON', 'USDT-EUL', 'BTC-KAVA', 'BTC-SC', 'KRW-ZIL', 'USDT-PROVE', 'USDT-TRX', 'BTC-ASTR', 'KRW-GAME2', 'KRW-STX', 'BTC-MAGIC', 'KRW-FLOCK', 'KRW-PROVE', 'BTC-ATH', 'USDT-RVN', 'BTC-NMR', 'USDT-INIT', 'KRW-BSV', 'KRW-SUI', 'BTC-ATM', 'KRW-SYRUP', 'KRW-BTC', 'BTC-TT', 'BTC-RVN', 'BTC-HBD', 'KRW-HOLO', 'KRW-MIRA', 'BTC-OPEN', 'KRW-SUN', 'KRW-ZBT', 'BTC-MANA', 'KRW-ONG', 'KRW-BTT', 'BTC-OCEAN', 'KRW-ENSO', 'BTC-PSG', 'BTC-PYTH', 'USDT-YB', 'USDT-SOON', 'BTC-POL', 'BTC-MET2', 'KRW-ONT', 'KRW-SOMI', 'USDT-BABY', 'BTC-CVC', 'BTC-NKN', 'BTC-RSR', 'KRW-DEEP', 'BTC-ARB', 'BTC-AERGO', 'USDT-DEEP', 'BTC-ARK', 'KRW-STRAX', 'BTC-STORJ', 'BTC-BLAST', 'USDT-BRETT', 'KRW-BREV', 'BTC-META', 'USDT-SYRUP', 'BTC-DENT', 'KRW-ICX', 'USDT-SOMI', 'KRW-POLYX', 'USDT-BREV']

stop_event = threading.Event()

def on_open(ws):
    subscribe_message = [
        {"ticket": str(uuid.uuid4())},
        {"type": "ticker", "codes": CODES},
    ]
    ws.send(json.dumps(subscribe_message))
    print("✅ connected")

def on_message(ws, message):
    if isinstance(message, (bytes, bytearray)):
        message = message.decode("utf-8")
    data = json.loads(message)

    # 버퍼에 추가
    try:
        ts = datetime.fromtimestamp(data.get("timestamp", 0) / 1000)
        row = [
            ts,
            data.get("code", ""),
            data.get("opening_price", 0),
            data.get("high_price", 0),
            data.get("low_price", 0),
            data.get("trade_price", 0),
            data.get("prev_closing_price", 0),
            data.get("change", ""),
            data.get("change_price", 0),
            data.get("signed_change_price", 0),
            data.get("change_rate", 0),
            data.get("signed_change_rate", 0),
            data.get("trade_volume", 0),
            data.get("acc_trade_volume", 0),
            data.get("acc_trade_volume_24h", 0),
            data.get("acc_trade_price", 0),
            data.get("acc_trade_price_24h", 0),
            data.get("trade_timestamp", 0),
            data.get("ask_bid", ""),
            data.get("acc_ask_volume", 0),
            data.get("acc_bid_volume", 0),
        ]
        with buffer_lock:
            buffer.append(row)
            should_flush = len(buffer) >= BATCH_SIZE

        # BATCH_SIZE에 도달하면 즉시 flush (lock 밖에서)
        if should_flush:
            flush_buffer()
    except Exception as e:
        print(f"❌ Buffer error: {e}")

def on_error(ws, error):
    # 에러가 나면 연결을 끊어 재연결 루프로 넘어가게 함
    print("❌ error:", error)

def on_close(ws, code, msg):
    print("🔌 closed:", code, msg)

def run_once():
    ws = websocket.WebSocketApp(
        WS_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    # 별도 스레드에서 run_forever 실행
    t = threading.Thread(
        target=lambda: ws.run_forever(ping_interval=30, ping_timeout=10),
        daemon=True
    )
    t.start()

    try:
        # 메인 스레드는 stop_event만 기다림 (Ctrl+C가 잘 들어옴)
        while not stop_event.is_set():
            time.sleep(0.2)
    finally:
        # 종료 시 소켓 닫고 스레드 정리
        ws.close()
        t.join(timeout=2)

if __name__ == "__main__":
    init_clickhouse()

    # flush 스레드 시작
    ft = threading.Thread(target=flush_thread, daemon=True)
    ft.start()

    # stats 스레드 시작
    st = threading.Thread(target=stats_thread, daemon=True)
    st.start()

    try:
        while True:
            run_once()
            if stop_event.is_set():
                break
            # 여기까지 왔으면 끊긴 거라 재연결
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Ctrl+C received. stopping...")
        stop_event.set()
