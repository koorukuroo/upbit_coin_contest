/**
 * Trading API Client
 * API Key 기반 트레이딩 API 호출
 */
class TradingAPI {
    constructor() {
        this.baseUrl = '';
        this.apiKey = localStorage.getItem('trading_api_key');
    }

    /**
     * API Key 설정
     */
    setApiKey(key) {
        this.apiKey = key;
        localStorage.setItem('trading_api_key', key);
    }

    /**
     * API Key 제거
     */
    clearApiKey() {
        this.apiKey = null;
        localStorage.removeItem('trading_api_key');
    }

    /**
     * API Key 헤더 포함 fetch
     */
    async fetchWithApiKey(url, options = {}) {
        if (!this.apiKey) {
            throw new Error('API Key not set');
        }

        const headers = {
            'Content-Type': 'application/json',
            'X-API-Key': this.apiKey,
            ...options.headers
        };

        const response = await fetch(url, { ...options, headers });

        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
            throw new Error(error.detail || `HTTP ${response.status}`);
        }

        return response.json();
    }

    // ============ 잔고/포지션 ============

    /**
     * 잔고 조회
     */
    async getBalance() {
        return this.fetchWithApiKey('/api/trading/balance');
    }

    /**
     * 포지션 조회
     */
    async getPositions() {
        return this.fetchWithApiKey('/api/trading/positions');
    }

    // ============ 주문 ============

    /**
     * 시장가 주문
     */
    async createMarketOrder(code, side, quantity, currentPrice) {
        return this.fetchWithApiKey(`/api/trading/orders?current_price=${currentPrice}`, {
            method: 'POST',
            body: JSON.stringify({
                code,
                side,
                order_type: 'market',
                quantity
            })
        });
    }

    /**
     * 지정가 주문
     */
    async createLimitOrder(code, side, quantity, price, currentPrice) {
        return this.fetchWithApiKey(`/api/trading/orders?current_price=${currentPrice}`, {
            method: 'POST',
            body: JSON.stringify({
                code,
                side,
                order_type: 'limit',
                quantity,
                price
            })
        });
    }

    /**
     * 주문 목록 조회
     */
    async getOrders(status = null, limit = 50) {
        let url = `/api/trading/orders?limit=${limit}`;
        if (status) url += `&status=${status}`;
        return this.fetchWithApiKey(url);
    }

    /**
     * 주문 취소
     */
    async cancelOrder(orderId) {
        return this.fetchWithApiKey(`/api/trading/orders/${orderId}`, {
            method: 'DELETE'
        });
    }

    /**
     * 거래 내역 조회
     */
    async getTrades(limit = 50) {
        return this.fetchWithApiKey(`/api/trading/trades?limit=${limit}`);
    }

    // ============ 대회 ============

    /**
     * 대회 목록 조회
     */
    async getCompetitions(status = null) {
        let url = '/api/competitions';
        if (status) url += `?status=${status}`;
        const response = await fetch(url);
        return response.json();
    }

    /**
     * 활성 대회 조회
     */
    async getActiveCompetition() {
        const response = await fetch('/api/competitions/active');
        return response.json();
    }

    /**
     * 대회 상세 조회
     */
    async getCompetition(competitionId) {
        const response = await fetch(`/api/competitions/${competitionId}`);
        return response.json();
    }

    /**
     * 대회 참가
     */
    async joinCompetition(competitionId) {
        return this.fetchWithApiKey(`/api/competitions/${competitionId}/join`, {
            method: 'POST'
        });
    }

    /**
     * 리더보드 조회
     */
    async getLeaderboard(competitionId, currentPrices = null) {
        let url = `/api/competitions/${competitionId}/leaderboard`;
        if (currentPrices) {
            url += `?current_prices=${encodeURIComponent(JSON.stringify(currentPrices))}`;
        }
        const response = await fetch(url);
        return response.json();
    }

    /**
     * 내 참가 상태 조회
     */
    async getMyStatus(competitionId) {
        return this.fetchWithApiKey(`/api/competitions/${competitionId}/my-status`);
    }

    // ============ 시세 데이터 ============

    /**
     * 최신 시세 조회
     */
    async getLatestPrice(code) {
        const response = await fetch(`/tickers/${code}/latest`);
        return response.json();
    }

    /**
     * 캔들 데이터 조회
     */
    async getCandles(code, interval = '1m', limit = 100) {
        const response = await fetch(`/candles/${code}?interval=${interval}&limit=${limit}`);
        return response.json();
    }

    /**
     * 지원 코드 목록
     */
    async getCodes() {
        const response = await fetch('/codes');
        return response.json();
    }
}

/**
 * Admin API Client
 * Clerk JWT 기반 관리자 API 호출
 */
class AdminAPI {
    constructor() {
        this.baseUrl = '';
    }

    /**
     * Clerk JWT 토큰 가져오기
     */
    async getClerkToken() {
        // Clerk이 로드될 때까지 대기
        if (typeof window.Clerk === 'undefined') {
            throw new Error('Clerk not loaded');
        }

        // Clerk 초기화 대기
        await window.Clerk.load();

        if (!window.Clerk.session) {
            throw new Error('Not logged in');
        }

        const token = await window.Clerk.session.getToken();
        if (!token) {
            throw new Error('Failed to get session token');
        }

        return token;
    }

    /**
     * Authorization 헤더 포함 fetch (Clerk JWT)
     */
    async fetchWithAuth(url, options = {}) {
        const token = await this.getClerkToken();

        const headers = {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
            ...options.headers
        };

        const response = await fetch(url, { ...options, headers });

        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
            throw new Error(error.detail || `HTTP ${response.status}`);
        }

        return response.json();
    }

    // ============ 통계 ============

    /**
     * 관리자 통계 조회
     */
    async getStats() {
        return this.fetchWithAuth('/api/admin/stats');
    }

    // ============ 대회 관리 ============

    /**
     * 모든 대회 목록 (관리자용)
     */
    async getCompetitions() {
        return this.fetchWithAuth('/api/admin/competitions');
    }

    /**
     * 대회 생성
     */
    async createCompetition(data) {
        return this.fetchWithAuth('/api/admin/competitions', {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }

    /**
     * 대회 수정
     */
    async updateCompetition(competitionId, data) {
        return this.fetchWithAuth(`/api/admin/competitions/${competitionId}/full`, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    }

    /**
     * 대회 활성화
     */
    async activateCompetition(competitionId) {
        return this.fetchWithAuth(`/api/admin/competitions/${competitionId}/activate`, {
            method: 'POST'
        });
    }

    /**
     * 대회 종료
     */
    async endCompetition(competitionId) {
        return this.fetchWithAuth(`/api/admin/competitions/${competitionId}/end`, {
            method: 'POST'
        });
    }

    /**
     * 대회 삭제
     */
    async deleteCompetition(competitionId) {
        return this.fetchWithAuth(`/api/admin/competitions/${competitionId}`, {
            method: 'DELETE'
        });
    }

    // ============ 참가자 관리 ============

    /**
     * 대회 참가자 목록 (실명 포함)
     */
    async getCompetitionParticipants(competitionId, currentPrices = null) {
        let url = `/api/admin/competitions/${competitionId}/participants`;
        if (currentPrices) {
            url += `?current_prices=${encodeURIComponent(currentPrices)}`;
        }
        return this.fetchWithAuth(url);
    }

    /**
     * 상금 지급
     */
    async awardParticipant(competitionId, data) {
        return this.fetchWithAuth(`/api/admin/competitions/${competitionId}/award`, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }

    // ============ 사용자 관리 ============

    /**
     * 사용자 목록
     */
    async getUsers(limit = 50) {
        return this.fetchWithAuth(`/api/admin/users?limit=${limit}`);
    }

    /**
     * 사용자를 관리자로 승격
     */
    async makeAdmin(userId) {
        return this.fetchWithAuth(`/api/admin/users/${userId}/make-admin`, {
            method: 'POST'
        });
    }

    // ============ 참가자 상세 ============

    /**
     * 참가자 상세 정보 조회
     */
    async getParticipant(participantId) {
        return this.fetchWithAuth(`/api/admin/participants/${participantId}`);
    }

    /**
     * 참가자 주문 내역 조회
     */
    async getParticipantOrders(participantId, { status = '', limit = 20, offset = 0 } = {}) {
        let url = `/api/admin/participants/${participantId}/orders?limit=${limit}&offset=${offset}`;
        if (status) url += `&status=${status}`;
        return this.fetchWithAuth(url);
    }

    /**
     * 참가자 거래 내역 조회
     */
    async getParticipantTrades(participantId, { limit = 20, offset = 0 } = {}) {
        return this.fetchWithAuth(`/api/admin/participants/${participantId}/trades?limit=${limit}&offset=${offset}`);
    }
}

// 전역 인스턴스
const tradingAPI = new TradingAPI();
const adminAPI = new AdminAPI();

// 관리자 링크 표시 (페이지 로드 시 자동 실행)
async function checkAndShowAdminLink() {
    const adminLink = document.getElementById('admin-link');
    if (!adminLink) return;

    try {
        // Clerk 로드 대기
        if (typeof window.Clerk === 'undefined') return;
        await window.Clerk.load();

        if (!window.Clerk.session) return;

        const token = await window.Clerk.session.getToken();
        if (!token) return;

        // 관리자 권한 확인
        const response = await fetch('/api/admin/stats', {
            headers: { 'Authorization': `Bearer ${token}` }
        });

        if (response.ok) {
            adminLink.style.display = 'inline';
        }
    } catch (e) {
        // 권한 없음 - 무시
    }
}

// DOM 로드 후 실행
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        setTimeout(checkAndShowAdminLink, 500);
    });
} else {
    setTimeout(checkAndShowAdminLink, 500);
}
