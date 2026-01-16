/**
 * Clerk 인증 관리
 */
class AuthManager {
    constructor() {
        this.clerk = null;
        this.user = null;
        this.apiKeys = [];
        this.initialized = false;
    }

    /**
     * Clerk 초기화
     */
    async init(publishableKey) {
        if (this.initialized) return;

        // Clerk SDK 로드 확인
        if (!window.Clerk) {
            console.error('Clerk SDK not loaded');
            return;
        }

        this.clerk = window.Clerk;
        await this.clerk.load();

        // 로그인 상태 확인
        if (this.clerk.user) {
            await this.registerUser();
        }

        this.initialized = true;
        this.updateUI();
    }

    /**
     * 백엔드에 사용자 등록
     */
    async registerUser() {
        if (!this.clerk.session) return;

        try {
            const token = await this.clerk.session.getToken();
            const response = await fetch('/api/auth/register', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            });

            if (response.ok) {
                this.user = await response.json();
                console.log('User registered:', this.user);
            }
        } catch (error) {
            console.error('Failed to register user:', error);
        }
    }

    /**
     * 로그인 상태 확인
     */
    isLoggedIn() {
        return !!this.clerk?.user;
    }

    /**
     * 현재 사용자 정보
     */
    getUser() {
        return this.user;
    }

    /**
     * Clerk JWT 토큰 얻기
     */
    async getToken() {
        if (!this.clerk?.session) return null;
        return this.clerk.session.getToken();
    }

    /**
     * API Key 목록 조회
     */
    async fetchApiKeys() {
        const token = await this.getToken();
        if (!token) return [];

        try {
            const response = await fetch('/api/keys', {
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });

            if (response.ok) {
                this.apiKeys = await response.json();
                return this.apiKeys;
            }
        } catch (error) {
            console.error('Failed to fetch API keys:', error);
        }
        return [];
    }

    /**
     * API Key 생성
     */
    async createApiKey(name = 'Default') {
        const token = await this.getToken();
        if (!token) throw new Error('Not logged in');

        const response = await fetch('/api/keys', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ name })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to create API key');
        }

        const newKey = await response.json();
        await this.fetchApiKeys();
        return newKey;
    }

    /**
     * API Key 삭제
     */
    async deleteApiKey(keyId) {
        const token = await this.getToken();
        if (!token) throw new Error('Not logged in');

        const response = await fetch(`/api/keys/${keyId}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });

        if (!response.ok) {
            throw new Error('Failed to delete API key');
        }

        await this.fetchApiKeys();
    }

    /**
     * 로그인 모달 열기
     */
    openSignIn() {
        if (this.clerk) {
            this.clerk.openSignIn();
        }
    }

    /**
     * 회원가입 모달 열기
     */
    openSignUp() {
        if (this.clerk) {
            this.clerk.openSignUp();
        }
    }

    /**
     * 로그아웃
     */
    async signOut() {
        if (this.clerk) {
            await this.clerk.signOut();
            this.user = null;
            this.apiKeys = [];
            tradingAPI.clearApiKey();
            this.updateUI();
        }
    }

    /**
     * UI 업데이트 (오버라이드 가능)
     */
    updateUI() {
        // 로그인/로그아웃 버튼 토글
        const loginBtn = document.getElementById('login-btn');
        const logoutBtn = document.getElementById('logout-btn');
        const userInfo = document.getElementById('user-info');

        if (this.isLoggedIn()) {
            if (loginBtn) loginBtn.style.display = 'none';
            if (logoutBtn) logoutBtn.style.display = 'block';
            if (userInfo) {
                userInfo.style.display = 'block';
                const emailEl = userInfo.querySelector('.user-email');
                if (emailEl) {
                    emailEl.textContent = this.clerk.user?.primaryEmailAddress?.emailAddress || '';
                }
            }
        } else {
            if (loginBtn) loginBtn.style.display = 'block';
            if (logoutBtn) logoutBtn.style.display = 'none';
            if (userInfo) userInfo.style.display = 'none';
        }

        // 커스텀 이벤트 발생
        window.dispatchEvent(new CustomEvent('auth-changed', {
            detail: { isLoggedIn: this.isLoggedIn(), user: this.user }
        }));
    }

    /**
     * 인증 상태 변경 리스너 등록
     */
    onAuthChange(callback) {
        window.addEventListener('auth-changed', (e) => callback(e.detail));
    }
}

// 전역 인스턴스
const authManager = new AuthManager();
