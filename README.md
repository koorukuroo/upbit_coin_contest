# Upbit 모의 투자 대회 시스템

[English](#english) | [한국어](#한국어)

---

## 한국어

실시간 Upbit 시세를 기반으로 한 모의 투자 대회 플랫폼입니다.

### 주요 기능

- 실시간 Upbit 시세 수신 및 캔들 차트 표시
- Clerk 인증 기반 사용자 관리
- API Key 발급 및 트레이딩
- 시장가/지정가 주문 지원
- 0.05% 수수료 적용
- 리더보드 순위 시스템

### 기술 스택

| 항목 | 기술 |
|------|------|
| Backend | FastAPI (Python) |
| 시세 DB | ClickHouse |
| 사용자 DB | PostgreSQL |
| 캐시 | Redis |
| 인증 | Clerk |
| 프록시 | Caddy (자동 HTTPS) |
| Frontend | Vanilla JS + LightweightCharts |

### 설치

```bash
# 저장소 클론
git clone https://github.com/your-username/upbit-coin-contest.git
cd upbit-coin-contest

# 의존성 설치
pip install -r requirements.txt

# 환경변수 설정
cp .env.example .env
# .env 파일을 편집하여 실제 값 입력
```

### 환경변수 설정

`.env.example` 파일을 참고하여 `.env` 파일을 생성하세요. 주요 설정:

- **POSTGRES_URL**: PostgreSQL 연결 문자열
- **CLICKHOUSE_***: ClickHouse 연결 정보
- **REDIS_***: Redis 연결 정보 (선택사항)
- **CLERK_***: Clerk 인증 키 ([clerk.com](https://clerk.com)에서 발급)
- **ADMIN_EMAILS**: 관리자 이메일 (쉼표로 구분)

### 데이터베이스 초기화

```bash
# PostgreSQL 테이블 생성
python init_db.py
```

### 실행

```bash
# API 서버 실행
python api.py

# 또는 uvicorn으로 실행
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

### API 엔드포인트

#### 공개 API

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/` | 메인 대시보드 |
| GET | `/candles/{code}` | 캔들 데이터 조회 |
| GET | `/tickers` | 최근 시세 조회 |
| WS | `/ws` | 실시간 시세 스트리밍 |

#### 인증 API (Clerk JWT)

| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/api/auth/register` | 사용자 등록 |
| GET | `/api/auth/me` | 내 정보 |

#### API Key 관리 (Clerk JWT)

| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/api/keys` | API Key 발급 |
| GET | `/api/keys` | API Key 목록 |
| DELETE | `/api/keys/{id}` | API Key 삭제 |

#### 대회 API

| Method | Endpoint | 설명 | 인증 |
|--------|----------|------|------|
| GET | `/api/competitions` | 대회 목록 | - |
| POST | `/api/competitions/{id}/join` | 대회 참가 | API Key |
| GET | `/api/competitions/{id}/leaderboard` | 리더보드 | - |

#### 트레이딩 API (API Key)

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/api/trading/balance` | 잔고 조회 |
| GET | `/api/trading/positions` | 보유 코인 |
| POST | `/api/trading/orders` | 주문 생성 |
| GET | `/api/trading/orders` | 주문 내역 |
| DELETE | `/api/trading/orders/{id}` | 주문 취소 |
| GET | `/api/trading/trades` | 거래 내역 |

### WebSocket API

```javascript
const ws = new WebSocket('ws://localhost:8000/ws');

ws.onopen = () => {
  // 전체 코인 구독
  ws.send(JSON.stringify({ subscribe: 'all' }));

  // 또는 특정 코인만 구독
  ws.send(JSON.stringify({ subscribe: ['KRW-BTC', 'KRW-ETH'] }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(data.code, data.trade_price);
};
```

### 지원 코인

- KRW-BTC, KRW-ETH, KRW-XRP, KRW-SOL, KRW-DOGE
- KRW-ADA, KRW-AVAX, KRW-DOT, KRW-LINK, KRW-MATIC

### 프로젝트 구조

```
upbit-coin-contest/
├── api.py                # 메인 API 서버
├── config.py             # 환경변수 설정
├── database.py           # PostgreSQL 연결
├── cache.py              # Redis 캐시
├── init_db.py            # DB 초기화 스크립트
│
├── models/               # SQLAlchemy 모델
│   ├── user.py
│   ├── api_key.py
│   ├── competition.py
│   ├── participant.py
│   ├── position.py
│   ├── order.py
│   └── trade.py
│
├── routers/              # API 라우터
│   ├── auth.py           # Clerk 인증
│   ├── keys.py           # API Key 관리
│   ├── competitions.py   # 대회 관련
│   ├── trading.py        # 주문/거래
│   └── admin.py          # 관리자
│
├── services/             # 비즈니스 로직
│   ├── order_service.py  # 주문 처리
│   └── matching_engine.py  # 지정가 체결
│
├── middleware/           # 미들웨어
│   └── api_key_auth.py   # API Key 인증
│
├── frontend/             # 프론트엔드
│   ├── index.html        # 메인 대시보드
│   ├── app.js            # 메인 JS
│   └── competition/      # 대회 페이지
│
├── migrations/           # DB 마이그레이션
│   └── 001_initial.sql
│
├── Caddyfile             # Caddy 설정
├── docker-compose.yml    # Docker 설정
├── requirements.txt      # Python 의존성
├── .env.example          # 환경변수 템플릿
└── LICENSE               # MIT 라이선스
```

### 프로덕션 배포

#### Caddy 설정 (HTTPS)

```
your-domain.com {
    reverse_proxy localhost:8000
}
```

```bash
# Caddy 설치 (Ubuntu)
sudo apt install caddy

# 설정 적용
sudo cp Caddyfile /etc/caddy/Caddyfile
sudo systemctl restart caddy
```

#### systemd 서비스

```ini
# /etc/systemd/system/upbit-api.service
[Unit]
Description=Upbit Trading API
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/path/to/upbit-coin-contest
ExecStart=/usr/bin/python api.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable upbit-api
sudo systemctl start upbit-api
```

---

## English

A mock cryptocurrency trading contest platform based on real-time Upbit market data.

### Features

- Real-time Upbit price feed with candlestick charts
- User management with Clerk authentication
- API Key issuance for programmatic trading
- Market and limit order support
- 0.05% trading fee simulation
- Leaderboard ranking system

### Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | FastAPI (Python) |
| Price DB | ClickHouse |
| User DB | PostgreSQL |
| Cache | Redis |
| Auth | Clerk |
| Proxy | Caddy (auto HTTPS) |
| Frontend | Vanilla JS + LightweightCharts |

### Quick Start

```bash
# Clone the repository
git clone https://github.com/your-username/upbit-coin-contest.git
cd upbit-coin-contest

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your actual values

# Initialize database
python init_db.py

# Run the server
python api.py
```

### Configuration

Copy `.env.example` to `.env` and configure:

- **POSTGRES_URL**: PostgreSQL connection string
- **CLICKHOUSE_***: ClickHouse connection details
- **REDIS_***: Redis connection (optional)
- **CLERK_***: Clerk authentication keys from [clerk.com](https://clerk.com)
- **ADMIN_EMAILS**: Admin email addresses (comma-separated)

### Supported Cryptocurrencies

BTC, ETH, XRP, SOL, DOGE, ADA, AVAX, DOT, LINK, MATIC (KRW pairs)

### Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
