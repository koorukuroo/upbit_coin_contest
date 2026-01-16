import json
import time
import uuid
import threading
import websocket

WS_URL = "wss://api.upbit.com/websocket/v1"
CODES = ["KRW-BTC", "KRW-ETH"]

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
    print(json.loads(message))

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
