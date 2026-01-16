-- 모의 투자 대회 시스템 초기 스키마
-- PostgreSQL 15+

-- UUID 확장 활성화
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 사용자 테이블
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clerk_user_id VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) NOT NULL,
    username VARCHAR(100),
    is_admin BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_clerk_user_id ON users(clerk_user_id);

-- API Keys 테이블
CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    api_key VARCHAR(64) UNIQUE NOT NULL,  -- SHA256 해시 저장
    api_key_prefix VARCHAR(8) NOT NULL,   -- 표시용 prefix
    name VARCHAR(100) DEFAULT 'Default',
    is_active BOOLEAN DEFAULT TRUE,
    last_used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_keys_api_key ON api_keys(api_key);
CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id);

-- 대회 테이블
CREATE TABLE IF NOT EXISTS competitions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    description TEXT,
    initial_balance DECIMAL(20, 8) NOT NULL DEFAULT 1000000,
    fee_rate DECIMAL(10, 8) NOT NULL DEFAULT 0.0005,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',  -- pending, active, ended
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_competitions_status ON competitions(status);

-- 참가자 테이블
CREATE TABLE IF NOT EXISTS participants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competition_id UUID NOT NULL REFERENCES competitions(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    balance DECIMAL(20, 8) NOT NULL,  -- 현재 KRW 잔고
    joined_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(competition_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_participants_competition ON participants(competition_id);
CREATE INDEX IF NOT EXISTS idx_participants_user ON participants(user_id);

-- 포지션 테이블 (보유 코인)
CREATE TABLE IF NOT EXISTS positions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    participant_id UUID NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    code VARCHAR(20) NOT NULL,         -- 코인 코드 (예: KRW-BTC)
    quantity DECIMAL(20, 8) NOT NULL,  -- 보유 수량
    avg_buy_price DECIMAL(20, 8) NOT NULL,  -- 평균 매수가
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(participant_id, code)
);

CREATE INDEX IF NOT EXISTS idx_positions_participant ON positions(participant_id);

-- 주문 테이블
CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    participant_id UUID NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    code VARCHAR(20) NOT NULL,         -- 코인 코드
    side VARCHAR(10) NOT NULL,         -- buy, sell
    order_type VARCHAR(10) NOT NULL,   -- market, limit
    price DECIMAL(20, 8),              -- 지정가 (시장가는 NULL)
    quantity DECIMAL(20, 8) NOT NULL,  -- 주문 수량
    filled_quantity DECIMAL(20, 8) DEFAULT 0,  -- 체결된 수량
    filled_price DECIMAL(20, 8),       -- 체결된 평균 가격
    fee DECIMAL(20, 8) DEFAULT 0,      -- 수수료
    status VARCHAR(20) DEFAULT 'pending',  -- pending, filled, partially_filled, cancelled
    created_at TIMESTAMP DEFAULT NOW(),
    filled_at TIMESTAMP,
    cancelled_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_orders_participant ON orders(participant_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_pending ON orders(code, status, order_type) WHERE status = 'pending';

-- 거래 내역 테이블
CREATE TABLE IF NOT EXISTS trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    participant_id UUID NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    code VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL,
    price DECIMAL(20, 8) NOT NULL,     -- 체결 가격
    quantity DECIMAL(20, 8) NOT NULL,  -- 체결 수량
    total_amount DECIMAL(20, 8) NOT NULL,  -- 총 금액
    fee DECIMAL(20, 8) NOT NULL,       -- 수수료
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trades_participant ON trades(participant_id);
CREATE INDEX IF NOT EXISTS idx_trades_order ON trades(order_id);

-- 업데이트 시간 자동 갱신 함수
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- 트리거 적용
DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_competitions_updated_at ON competitions;
CREATE TRIGGER update_competitions_updated_at
    BEFORE UPDATE ON competitions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_positions_updated_at ON positions;
CREATE TRIGGER update_positions_updated_at
    BEFORE UPDATE ON positions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
