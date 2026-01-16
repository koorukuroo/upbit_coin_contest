import json
import asyncio
import uuid
from datetime import datetime
from typing import Optional, Set
from contextlib import asynccontextmanager

import websockets
import clickhouse_connect
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from config import settings
from database import engine, get_db
from routers import (
    auth_router,
    keys_router,
    competitions_router,
    trading_router,
    admin_router
)
from services.matching_engine import process_ticker_for_matching
from database import async_session
from cache import init_cache, get_cache
from models.competition import Competition
from sqlalchemy import select, update

# ClickHouse 설정
CH_HOST = settings.CLICKHOUSE_HOST
CH_PORT = settings.CLICKHOUSE_PORT
CH_USER = settings.CLICKHOUSE_USER
CH_PASSWORD = settings.CLICKHOUSE_PASSWORD
CH_DATABASE = settings.CLICKHOUSE_DATABASE

# Upbit WebSocket
UPBIT_WS_URL = "wss://api.upbit.com/websocket/v1"
CODES = settings.SUPPORTED_CODES

# 전역 상태
ch_client = None
connected_clients: Set[WebSocket] = set()
subscriptions: dict[WebSocket, Set[str]] = {}  # 클라이언트별 구독 코드
postgres_available = False  # PostgreSQL 연결 상태

# 통계
stats = {"total_received": 0, "total_broadcast": 0}


def get_ch_client():
    global ch_client
    if ch_client is None:
        ch_client = clickhouse_connect.get_client(
            host=CH_HOST,
            port=CH_PORT,
            username=CH_USER,
            password=CH_PASSWORD,
            database=CH_DATABASE
        )
    return ch_client


async def broadcast(data: dict):
    """구독한 클라이언트들에게 데이터 전송"""
    code = data.get("code", "")
    message = json.dumps(data, default=str)

    disconnected = set()
    for client in connected_clients:
        # 해당 코드를 구독한 클라이언트에게만 전송
        client_subs = subscriptions.get(client, set())
        if not client_subs or code in client_subs:  # 빈 set이면 전체 구독
            try:
                await client.send_text(message)
                stats["total_broadcast"] += 1
            except:
                disconnected.add(client)

    # 끊긴 클라이언트 제거
    for client in disconnected:
        connected_clients.discard(client)
        subscriptions.pop(client, None)


async def update_competition_statuses():
    """대회 상태 자동 업데이트 (백그라운드 작업)

    - pending + start_time 지남 → active
    - active + end_time 지남 → ended
    """
    while True:
        try:
            await asyncio.sleep(30)  # 30초마다 체크

            async with async_session() as db:
                now = datetime.utcnow()

                # pending → active (시작 시간 지남)
                await db.execute(
                    update(Competition)
                    .where(
                        Competition.status == "pending",
                        Competition.start_time <= now
                    )
                    .values(status="active")
                )

                # active → ended (종료 시간 지남)
                await db.execute(
                    update(Competition)
                    .where(
                        Competition.status == "active",
                        Competition.end_time < now
                    )
                    .values(status="ended")
                )

                await db.commit()

        except Exception as e:
            print(f"⚠️ Competition status update error: {e}")


async def upbit_websocket_handler():
    """Upbit WebSocket에서 데이터를 받아 처리"""
    global postgres_available

    while True:
        try:
            async with websockets.connect(UPBIT_WS_URL) as ws:
                subscribe_msg = [
                    {"ticket": str(uuid.uuid4())},
                    {"type": "ticker", "codes": CODES},
                ]
                await ws.send(json.dumps(subscribe_msg))
                print("✅ Upbit WebSocket connected")

                async for message in ws:
                    if isinstance(message, bytes):
                        message = message.decode("utf-8")

                    data = json.loads(message)
                    stats["total_received"] += 1

                    # 클라이언트들에게 브로드캐스트
                    await broadcast(data)

                    # 지정가 주문 체결 확인 (PostgreSQL 연결 시에만)
                    if postgres_available:
                        try:
                            async with async_session() as db:
                                await process_ticker_for_matching(db, data)
                        except Exception as me_err:
                            pass  # 매칭 에러는 조용히 무시

        except Exception as e:
            print(f"❌ Upbit WebSocket error: {e}")
            await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global postgres_available

    # 시작 시
    get_ch_client()
    print("✅ ClickHouse connected")

    # Redis 연결
    redis_cache = await init_cache()

    # PostgreSQL 연결 테스트
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        postgres_available = True
        print("✅ PostgreSQL connected")
        print("✅ Matching engine ready")
    except Exception as e:
        postgres_available = False
        print(f"⚠️ PostgreSQL connection failed: {e}")
        print("  Trading features will be disabled")

    # Upbit WebSocket 태스크 시작
    ws_task = asyncio.create_task(upbit_websocket_handler())

    # 대회 상태 자동 업데이트 태스크 시작
    competition_task = asyncio.create_task(update_competition_statuses())
    print("✅ Competition status updater started")

    yield

    # 종료 시
    ws_task.cancel()
    competition_task.cancel()
    if redis_cache:
        await redis_cache.close()
    await engine.dispose()
    print("✅ Connections closed")


app = FastAPI(
    title="Upbit Trading Competition API",
    description="실시간 Upbit 시세 및 모의 투자 대회 API",
    lifespan=lifespan,
    docs_url="/swagger",  # Swagger UI를 /swagger로 이동
    redoc_url="/redoc",   # ReDoc은 /redoc 유지
    openapi_url="/openapi.json"
)

# CORS 미들웨어
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 라우터 등록
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(keys_router, prefix="/api/keys", tags=["keys"])
app.include_router(competitions_router, prefix="/api/competitions", tags=["competitions"])
app.include_router(trading_router, prefix="/api/trading", tags=["trading"])
app.include_router(admin_router, prefix="/api/admin", tags=["admin"])

# 정적 파일 서빙
app.mount("/static", StaticFiles(directory="frontend"), name="static")


# ============ REST API ============

@app.get("/")
async def root():
    """프론트엔드 페이지 서빙"""
    return FileResponse("frontend/index.html")


@app.get("/competition")
@app.get("/competition/")
async def competition_page():
    """대회 메인 페이지"""
    return FileResponse("frontend/competition/index.html")


@app.get("/competition/trading")
async def competition_trading_page():
    """트레이딩 페이지"""
    return FileResponse("frontend/competition/trading.html")


@app.get("/competition/leaderboard")
async def competition_leaderboard_page():
    """리더보드 페이지"""
    return FileResponse("frontend/competition/leaderboard.html")


@app.get("/docs")
async def api_docs_page():
    """API 문서 페이지"""
    return FileResponse("frontend/docs.html")


@app.get("/admin")
@app.get("/admin/")
async def admin_page():
    """관리자 페이지"""
    return FileResponse("frontend/admin/index.html")


@app.get("/admin/competitions/{competition_id}")
async def admin_competition_detail_page(competition_id: str):
    """관리자 대회 상세 페이지"""
    return FileResponse("frontend/admin/competition.html")


@app.get("/admin/participants/{participant_id}")
async def admin_participant_detail_page(participant_id: str):
    """관리자 참가자 상세 페이지"""
    return FileResponse("frontend/admin/participant.html")


@app.get("/api")
async def api_info():
    return {
        "message": "Upbit Trading Competition API",
        "market_data": {
            "GET /tickers": "시세 조회 (기간/코드 필터 가능)",
            "GET /tickers/{code}": "특정 코드 시세 조회",
            "GET /tickers/{code}/latest": "특정 코드 최신 시세",
            "GET /candles/{code}": "OHLCV 캔들 데이터",
            "GET /codes": "저장된 코드 목록",
            "WS /ws": "실시간 WebSocket 스트림"
        },
        "trading": {
            "POST /api/auth/register": "Clerk 인증 후 사용자 등록",
            "POST /api/keys": "API Key 발급",
            "GET /api/competitions": "대회 목록",
            "POST /api/competitions/{id}/join": "대회 참가",
            "GET /api/trading/balance": "잔고 조회",
            "POST /api/trading/orders": "주문 생성",
            "GET /api/competitions/{id}/leaderboard": "리더보드"
        },
        "documentation": {
            "GET /docs": "API 가이드 (친절한 설명)",
            "GET /swagger": "Swagger UI (인터랙티브 테스트)",
            "GET /redoc": "ReDoc (레퍼런스 문서)",
            "GET /openapi.json": "OpenAPI 스키마"
        }
    }


@app.get("/tickers")
async def get_tickers(
    code: Optional[str] = Query(default=None, description="코드 필터 (예: KRW-BTC)"),
    start: Optional[str] = Query(default=None, description="시작 시간 (예: 2026-01-09 00:00:00)"),
    end: Optional[str] = Query(default=None, description="종료 시간 (예: 2026-01-09 23:59:59)"),
    limit: int = Query(default=100, le=10000, description="최대 조회 수")
):
    """
    시세 조회 (기간 지정 가능)

    - code: 특정 코드만 조회
    - start: 시작 시간 (ISO 형식 또는 'YYYY-MM-DD HH:MM:SS')
    - end: 종료 시간
    - limit: 최대 조회 수 (기본 100, 최대 10000)
    """
    client = get_ch_client()

    conditions = []
    params = {"limit": limit}

    if code:
        conditions.append("code = {code:String}")
        params["code"] = code
    if start:
        conditions.append("timestamp >= {start:String}")
        params["start"] = start
    if end:
        conditions.append("timestamp <= {end:String}")
        params["end"] = end

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    result = client.query(f"""
        SELECT timestamp, code, trade_price, trade_volume, change, change_rate
        FROM upbit_ticker
        {where_clause}
        ORDER BY timestamp DESC
        LIMIT {{limit:UInt32}}
    """, parameters=params)

    return [
        {
            "timestamp": str(row[0]),
            "code": row[1],
            "trade_price": row[2],
            "trade_volume": row[3],
            "change": row[4],
            "change_rate": row[5]
        }
        for row in result.result_rows
    ]


@app.get("/tickers/{code}")
async def get_ticker_by_code(code: str, limit: int = Query(default=100, le=1000)):
    """특정 코드 시세 조회"""
    client = get_ch_client()
    result = client.query("""
        SELECT timestamp, code, trade_price, trade_volume, change, change_rate
        FROM upbit_ticker
        WHERE code = {code:String}
        ORDER BY timestamp DESC
        LIMIT {limit:UInt32}
    """, parameters={"code": code, "limit": limit})

    return [
        {
            "timestamp": str(row[0]),
            "code": row[1],
            "trade_price": row[2],
            "trade_volume": row[3],
            "change": row[4],
            "change_rate": row[5]
        }
        for row in result.result_rows
    ]


@app.get("/tickers/{code}/latest")
async def get_latest_ticker(code: str):
    """특정 코드 최신 시세"""
    # 캐시 키 생성
    cache_key = f"ticker:latest:{code}"

    # 캐시에서 조회
    cache = await get_cache()
    if cache and cache.is_connected:
        cached = await cache.get(cache_key)
        if cached:
            return cached

    client = get_ch_client()
    result = client.query("""
        SELECT timestamp, code, opening_price, high_price, low_price, trade_price,
               prev_closing_price, change, change_price, change_rate,
               trade_volume, acc_trade_volume_24h, acc_trade_price_24h
        FROM upbit_ticker
        WHERE code = {code:String}
        ORDER BY timestamp DESC
        LIMIT 1
    """, parameters={"code": code})

    if not result.result_rows:
        return JSONResponse(status_code=404, content={"error": "Not found"})

    row = result.result_rows[0]
    data = {
        "timestamp": str(row[0]),
        "code": row[1],
        "opening_price": row[2],
        "high_price": row[3],
        "low_price": row[4],
        "trade_price": row[5],
        "prev_closing_price": row[6],
        "change": row[7],
        "change_price": row[8],
        "change_rate": row[9],
        "trade_volume": row[10],
        "acc_trade_volume_24h": row[11],
        "acc_trade_price_24h": row[12]
    }

    # 캐시에 저장 (1초 TTL)
    if cache and cache.is_connected:
        await cache.set(cache_key, data, settings.CACHE_TTL_TICKERS)

    return data


@app.get("/candles/{code}")
async def get_candles(
    code: str,
    interval: str = Query(default="1m", description="간격 (1m, 5m, 15m, 1h, 1d)"),
    start: Optional[str] = Query(default=None, description="시작 시간"),
    end: Optional[str] = Query(default=None, description="종료 시간"),
    limit: int = Query(default=100, le=1000, description="최대 조회 수")
):
    """
    OHLCV 캔들 데이터 조회

    - interval: 1m(1분), 5m(5분), 15m(15분), 1h(1시간), 1d(1일)
    """
    # 캐시 키 생성
    cache_key = f"candles:{code}:{interval}:{start}:{end}:{limit}"

    # 캐시에서 조회
    cache = await get_cache()
    if cache and cache.is_connected:
        cached = await cache.get(cache_key)
        if cached:
            return cached

    client = get_ch_client()

    # interval to seconds
    interval_map = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1h": 3600,
        "1d": 86400
    }
    seconds = interval_map.get(interval, 60)

    conditions = ["code = {code:String}"]
    params = {"code": code, "limit": limit, "seconds": seconds}

    if start:
        conditions.append("timestamp >= {start:String}")
        params["start"] = start
    if end:
        conditions.append("timestamp <= {end:String}")
        params["end"] = end

    where_clause = f"WHERE {' AND '.join(conditions)}"

    result = client.query(f"""
        SELECT
            toStartOfInterval(timestamp, INTERVAL {{seconds:UInt32}} SECOND) as candle_time,
            argMin(trade_price, timestamp) as open,
            max(trade_price) as high,
            min(trade_price) as low,
            argMax(trade_price, timestamp) as close,
            sum(trade_volume) as volume,
            count() as trade_count
        FROM upbit_ticker
        {where_clause}
        GROUP BY candle_time
        ORDER BY candle_time DESC
        LIMIT {{limit:UInt32}}
    """, parameters=params)

    data = [
        {
            "time": str(row[0]),
            "open": row[1],
            "high": row[2],
            "low": row[3],
            "close": row[4],
            "volume": row[5],
            "trade_count": row[6]
        }
        for row in result.result_rows
    ]

    # 캐시에 저장 (5초 TTL)
    if cache and cache.is_connected:
        await cache.set(cache_key, data, settings.CACHE_TTL_CANDLES)

    return data


@app.get("/candles/{code}/export")
async def export_candles(
    code: str,
    interval: str = Query(default="1m", description="간격 (1m, 5m, 15m, 1h, 1d)"),
    start: Optional[str] = Query(default=None, description="시작 시간"),
    end: Optional[str] = Query(default=None, description="종료 시간"),
    format: str = Query(default="csv", description="포맷 (csv, json)"),
    limit: int = Query(default=10000, le=100000, description="최대 조회 수")
):
    """
    OHLCV 캔들 데이터 다운로드 (덤프)

    - interval: 1m(1분), 5m(5분), 15m(15분), 1h(1시간), 1d(1일)
    - format: csv 또는 json
    - limit: 최대 조회 수 (기본 10000, 최대 100000)
    """
    client = get_ch_client()

    # interval to seconds
    interval_map = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1h": 3600,
        "1d": 86400
    }
    seconds = interval_map.get(interval, 60)

    conditions = ["code = {code:String}"]
    params = {"code": code, "limit": limit, "seconds": seconds}

    if start:
        conditions.append("timestamp >= {start:String}")
        params["start"] = start
    if end:
        conditions.append("timestamp <= {end:String}")
        params["end"] = end

    where_clause = f"WHERE {' AND '.join(conditions)}"

    result = client.query(f"""
        SELECT
            toStartOfInterval(timestamp, INTERVAL {{seconds:UInt32}} SECOND) as candle_time,
            argMin(trade_price, timestamp) as open,
            max(trade_price) as high,
            min(trade_price) as low,
            argMax(trade_price, timestamp) as close,
            sum(trade_volume) as volume,
            count() as trade_count
        FROM upbit_ticker
        {where_clause}
        GROUP BY candle_time
        ORDER BY candle_time ASC
        LIMIT {{limit:UInt32}}
    """, parameters=params)

    rows = [
        {
            "time": str(row[0]),
            "open": row[1],
            "high": row[2],
            "low": row[3],
            "close": row[4],
            "volume": row[5],
            "trade_count": row[6]
        }
        for row in result.result_rows
    ]

    if format == "json":
        return JSONResponse(
            content={"code": code, "interval": interval, "count": len(rows), "data": rows},
            headers={
                "Content-Disposition": f'attachment; filename="{code}_{interval}.json"'
            }
        )
    else:  # CSV
        import io
        import csv

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["time", "open", "high", "low", "close", "volume", "trade_count"])
        for row in rows:
            writer.writerow([row["time"], row["open"], row["high"], row["low"], row["close"], row["volume"], row["trade_count"]])

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{code}_{interval}.csv"'
            }
        )


@app.get("/tickers/export")
async def export_tickers(
    code: Optional[str] = Query(default=None, description="코드 필터 (예: KRW-BTC)"),
    start: Optional[str] = Query(default=None, description="시작 시간"),
    end: Optional[str] = Query(default=None, description="종료 시간"),
    format: str = Query(default="csv", description="포맷 (csv, json)"),
    limit: int = Query(default=10000, le=100000, description="최대 조회 수")
):
    """
    시세 데이터 다운로드 (덤프)

    - format: csv 또는 json
    - limit: 최대 조회 수 (기본 10000, 최대 100000)
    """
    client = get_ch_client()

    conditions = []
    params = {"limit": limit}

    if code:
        conditions.append("code = {code:String}")
        params["code"] = code
    if start:
        conditions.append("timestamp >= {start:String}")
        params["start"] = start
    if end:
        conditions.append("timestamp <= {end:String}")
        params["end"] = end

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    result = client.query(f"""
        SELECT timestamp, code, trade_price, trade_volume, change, change_rate,
               opening_price, high_price, low_price, prev_closing_price
        FROM upbit_ticker
        {where_clause}
        ORDER BY timestamp ASC
        LIMIT {{limit:UInt32}}
    """, parameters=params)

    rows = [
        {
            "timestamp": str(row[0]),
            "code": row[1],
            "trade_price": row[2],
            "trade_volume": row[3],
            "change": row[4],
            "change_rate": row[5],
            "opening_price": row[6],
            "high_price": row[7],
            "low_price": row[8],
            "prev_closing_price": row[9]
        }
        for row in result.result_rows
    ]

    filename_prefix = code.replace("-", "_") if code else "all_tickers"

    if format == "json":
        return JSONResponse(
            content={"count": len(rows), "data": rows},
            headers={
                "Content-Disposition": f'attachment; filename="{filename_prefix}.json"'
            }
        )
    else:  # CSV
        import io
        import csv

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["timestamp", "code", "trade_price", "trade_volume", "change",
                        "change_rate", "opening_price", "high_price", "low_price", "prev_closing_price"])
        for row in rows:
            writer.writerow([row["timestamp"], row["code"], row["trade_price"], row["trade_volume"],
                           row["change"], row["change_rate"], row["opening_price"], row["high_price"],
                           row["low_price"], row["prev_closing_price"]])

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{filename_prefix}.csv"'
            }
        )


@app.get("/summary/{code}")
async def get_summary(
    code: str,
    start: Optional[str] = Query(default=None, description="시작 시간"),
    end: Optional[str] = Query(default=None, description="종료 시간")
):
    """기간 내 요약 통계"""
    client = get_ch_client()

    conditions = ["code = {code:String}"]
    params = {"code": code}

    if start:
        conditions.append("timestamp >= {start:String}")
        params["start"] = start
    if end:
        conditions.append("timestamp <= {end:String}")
        params["end"] = end

    where_clause = f"WHERE {' AND '.join(conditions)}"

    result = client.query(f"""
        SELECT
            min(timestamp) as first_time,
            max(timestamp) as last_time,
            argMin(trade_price, timestamp) as first_price,
            argMax(trade_price, timestamp) as last_price,
            min(trade_price) as low_price,
            max(trade_price) as high_price,
            avg(trade_price) as avg_price,
            sum(trade_volume) as total_volume,
            count() as trade_count
        FROM upbit_ticker
        {where_clause}
    """, parameters=params)

    if not result.result_rows or result.result_rows[0][0] is None:
        return JSONResponse(status_code=404, content={"error": "No data found"})

    row = result.result_rows[0]
    first_price = row[2]
    last_price = row[3]
    price_change = last_price - first_price
    price_change_rate = (price_change / first_price * 100) if first_price else 0

    return {
        "code": code,
        "first_time": str(row[0]),
        "last_time": str(row[1]),
        "first_price": first_price,
        "last_price": last_price,
        "low_price": row[4],
        "high_price": row[5],
        "avg_price": row[6],
        "price_change": price_change,
        "price_change_rate": round(price_change_rate, 4),
        "total_volume": row[7],
        "trade_count": row[8]
    }


@app.get("/codes")
async def get_codes():
    """저장된 코드 목록"""
    client = get_ch_client()
    result = client.query("""
        SELECT code, count() as cnt, max(timestamp) as last_update
        FROM upbit_ticker
        GROUP BY code
        ORDER BY cnt DESC
    """)

    return [
        {"code": row[0], "count": row[1], "last_update": str(row[2])}
        for row in result.result_rows
    ]


@app.get("/stats")
async def get_stats():
    """통계 조회"""
    client = get_ch_client()
    result = client.query("SELECT count() FROM upbit_ticker")
    total_rows = result.result_rows[0][0]

    return {
        "db_total_rows": total_rows,
        "ws_total_received": stats["total_received"],
        "ws_total_broadcast": stats["total_broadcast"],
        "ws_connected_clients": len(connected_clients)
    }


# ============ WebSocket API ============

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    실시간 WebSocket 스트림

    연결 후 구독할 코드를 JSON으로 전송:
    {"subscribe": ["KRW-BTC", "KRW-ETH"]}

    전체 구독:
    {"subscribe": "all"}
    """
    await websocket.accept()
    connected_clients.add(websocket)
    subscriptions[websocket] = set()  # 빈 set = 전체 구독

    print(f"📡 Client connected. Total: {len(connected_clients)}")

    try:
        while True:
            # 클라이언트로부터 구독 메시지 수신
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if "subscribe" in msg:
                    if msg["subscribe"] == "all":
                        subscriptions[websocket] = set()
                        await websocket.send_text(json.dumps({"status": "subscribed", "codes": "all"}))
                    else:
                        codes = set(msg["subscribe"])
                        subscriptions[websocket] = codes
                        await websocket.send_text(json.dumps({"status": "subscribed", "codes": list(codes)}))
            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        pass
    finally:
        connected_clients.discard(websocket)
        subscriptions.pop(websocket, None)
        print(f"📡 Client disconnected. Total: {len(connected_clients)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
