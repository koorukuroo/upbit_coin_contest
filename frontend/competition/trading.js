/**
 * Trading Page Logic
 */

// 상태
let selectedCode = 'KRW-BTC';
let currentSide = 'buy';
let currentOrderType = 'market';
let currentPrices = {};
let balance = 0;
let positions = [];
let ws = null;
let chart = null;
let candleSeries = null;
let volumeSeries = null;
let lastCandle = null;  // 마지막 캔들 추적
let lastVolume = 0;     // 마지막 캔들 거래량 누적
let candleDataMap = {}; // 시간별 캔들 데이터 (crosshair용)
let volumeDataMap = {}; // 시간별 거래량 데이터

// 지원 코인 목록
const CODES = ['KRW-BTC', 'KRW-ETH', 'KRW-XRP', 'KRW-SOL', 'KRW-DOGE',
               'KRW-ADA', 'KRW-AVAX', 'KRW-DOT', 'KRW-LINK', 'KRW-MATIC'];

// 초기화
document.addEventListener('DOMContentLoaded', async () => {
    // 이벤트 리스너 설정
    setupEventListeners();

    // 차트 초기화
    initChart();

    // 코인 목록 초기화
    renderCoinList();

    // WebSocket 연결
    connectWebSocket();

    // 캔들 로드
    loadCandles();

    // 30초마다 캔들 새로고침 (서버와 동기화)
    setInterval(loadCandles, 30000);

    // API Key가 있으면 데이터 로드
    if (tradingAPI && tradingAPI.apiKey) {
        await Promise.all([
            loadBalance(),
            loadPositions(),
            loadOrders(),
            loadTrades()
        ]);
    } else {
        document.getElementById('balance-krw').textContent = '로그인 필요';
        document.getElementById('balance-total').textContent = '-';
    }
});

// 에러 표시
function showError(message) {
    const container = document.getElementById('error-container');
    container.textContent = message;
    container.classList.remove('hidden');
}

// 이벤트 리스너 설정
function setupEventListeners() {
    // 매수/매도 탭
    document.querySelectorAll('.order-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.order-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            currentSide = tab.dataset.side;
            updateOrderButton();
            updateOrderSummary();
        });
    });

    // 주문 유형 (시장가/지정가)
    document.querySelectorAll('.order-type-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.order-type-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentOrderType = btn.dataset.type;

            const priceGroup = document.getElementById('limit-price-group');
            priceGroup.classList.toggle('hidden', currentOrderType === 'market');

            updateOrderSummary();
        });
    });

    // 퍼센트 버튼
    document.querySelectorAll('.percent-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const percent = parseInt(btn.dataset.percent);
            calculateQuantityByPercent(percent);
        });
    });

    // 수량/가격 입력
    document.getElementById('order-quantity').addEventListener('input', updateOrderSummary);
    document.getElementById('order-price').addEventListener('input', updateOrderSummary);

    // 주문 제출
    document.getElementById('submit-order').addEventListener('click', submitOrder);

    // 하단 탭
    document.querySelectorAll('.bottom-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.bottom-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            const tabName = tab.dataset.tab;
            document.querySelectorAll('.bottom-content > div').forEach(content => {
                content.classList.add('hidden');
            });
            document.getElementById(`${tabName}-content`).classList.remove('hidden');
        });
    });
}

// WebSocket 연결
function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    ws.onopen = () => {
        console.log('WebSocket connected');
        ws.send(JSON.stringify({ subscribe: CODES }));
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.code && data.trade_price) {
            currentPrices[data.code] = data.trade_price;
            updateCoinPrice(data);

            // 선택된 코인이면 차트 실시간 업데이트
            if (data.code === selectedCode) {
                updateChartRealtime(data);
            }

            // 보유 코인이면 총 평가자산 업데이트
            if (positions.some(p => p.code === data.code)) {
                updateTotalBalance();
                renderPositions();  // 평가금액도 업데이트
            }
        }
    };

    ws.onclose = () => {
        console.log('WebSocket disconnected, reconnecting...');
        setTimeout(connectWebSocket, 1000);
    };

    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
    };
}

// 코인 목록 렌더링
function renderCoinList() {
    const container = document.getElementById('coin-list-content');
    container.innerHTML = CODES.map(code => `
        <div class="coin-item ${code === selectedCode ? 'selected' : ''}" data-code="${code}">
            <div class="coin-name">${code.replace('KRW-', '')}</div>
            <div class="coin-price">
                <div class="price" id="price-${code}">-</div>
                <div class="change even" id="change-${code}">0.00%</div>
            </div>
        </div>
    `).join('');

    // 클릭 이벤트
    container.querySelectorAll('.coin-item').forEach(item => {
        item.addEventListener('click', () => {
            document.querySelectorAll('.coin-item').forEach(i => i.classList.remove('selected'));
            item.classList.add('selected');
            selectedCode = item.dataset.code;
            updateSelectedCoinDisplay();
            loadCandles();
        });
    });
}

// 코인 가격 업데이트
function updateCoinPrice(data) {
    const priceEl = document.getElementById(`price-${data.code}`);
    const changeEl = document.getElementById(`change-${data.code}`);

    if (priceEl) {
        priceEl.textContent = formatNumber(data.trade_price);
    }

    if (changeEl) {
        const changeRate = (data.change_rate * 100).toFixed(2);
        changeEl.textContent = `${data.change === 'RISE' ? '+' : ''}${changeRate}%`;
        changeEl.className = `change ${data.change === 'RISE' ? 'up' : data.change === 'FALL' ? 'down' : 'even'}`;
    }

    // 선택된 코인이면 상단도 업데이트
    if (data.code === selectedCode) {
        updateSelectedCoinDisplay();
    }
}

// 선택된 코인 표시 업데이트
function updateSelectedCoinDisplay() {
    const price = currentPrices[selectedCode];
    document.getElementById('selected-coin-name').textContent = selectedCode;
    document.getElementById('selected-coin-price').textContent = price ? formatNumber(price) + ' KRW' : '-';

    // 주문 요약 업데이트
    updateOrderSummary();
}

// 잔고 로드
async function loadBalance() {
    try {
        const data = await tradingAPI.getBalance();
        balance = data.balance;
        document.getElementById('balance-krw').textContent = formatNumber(balance) + ' KRW';
        updateTotalBalance();
    } catch (error) {
        console.error('Failed to load balance:', error);
        document.getElementById('balance-krw').textContent = '로드 실패';
    }
}

// 포지션 로드
async function loadPositions() {
    try {
        positions = await tradingAPI.getPositions();
        renderPositions();
        updateTotalBalance();
    } catch (error) {
        console.error('Failed to load positions:', error);
    }
}

// 포지션 렌더링
function renderPositions() {
    const container = document.getElementById('positions-list');

    if (positions.length === 0) {
        container.innerHTML = '<div style="padding: 1rem; color: #888; text-align: center;">보유 코인 없음</div>';
        return;
    }

    container.innerHTML = positions.map(pos => {
        const currentPrice = currentPrices[pos.code] || pos.avg_buy_price;
        const evalValue = pos.quantity * currentPrice;

        return `
            <div class="position-item">
                <span>${pos.code.replace('KRW-', '')}</span>
                <span>${formatQuantity(pos.quantity)}</span>
                <span>${formatNumber(pos.avg_buy_price)}</span>
                <span>${formatNumber(evalValue)}</span>
            </div>
        `;
    }).join('');
}

// 총 평가자산 업데이트
function updateTotalBalance() {
    let coinValue = 0;
    positions.forEach(pos => {
        const price = currentPrices[pos.code] || pos.avg_buy_price;
        coinValue += pos.quantity * price;
    });

    const total = balance + coinValue;
    document.getElementById('balance-total').textContent = formatNumber(total) + ' KRW';
}

// 주문 목록 로드
async function loadOrders() {
    try {
        const orders = await tradingAPI.getOrders('pending');
        renderOrders(orders);
    } catch (error) {
        console.error('Failed to load orders:', error);
    }
}

// 주문 렌더링
function renderOrders(orders) {
    const container = document.getElementById('orders-list');

    if (orders.length === 0) {
        container.innerHTML = '<div style="padding: 1rem; color: #888; text-align: center;">미체결 주문 없음</div>';
        return;
    }

    container.innerHTML = orders.map(order => `
        <div class="order-list-item">
            <span>${order.code.replace('KRW-', '')}</span>
            <span style="color: ${order.side === 'buy' ? '#ef5350' : '#26a69a'}">${order.side === 'buy' ? '매수' : '매도'}</span>
            <span>${formatNumber(order.price)}</span>
            <span>${formatQuantity(order.quantity)}</span>
            <span><button class="cancel-btn" onclick="cancelOrder('${order.id}')">취소</button></span>
        </div>
    `).join('');
}

// 거래 내역 로드
async function loadTrades() {
    try {
        const trades = await tradingAPI.getTrades();
        renderTrades(trades);
    } catch (error) {
        console.error('Failed to load trades:', error);
    }
}

// 거래 내역 렌더링
function renderTrades(trades) {
    const container = document.getElementById('trades-list');

    if (trades.length === 0) {
        container.innerHTML = '<div style="padding: 1rem; color: #888; text-align: center;">거래 내역 없음</div>';
        return;
    }

    container.innerHTML = trades.slice(0, 20).map(trade => {
        const time = new Date(trade.created_at).toLocaleTimeString('ko-KR', { timeZone: 'Asia/Seoul' });
        return `
            <div class="trade-list-item">
                <span>${time}</span>
                <span>${trade.code.replace('KRW-', '')}</span>
                <span style="color: ${trade.side === 'buy' ? '#ef5350' : '#26a69a'}">${trade.side === 'buy' ? '매수' : '매도'}</span>
                <span>${formatNumber(trade.price)}</span>
                <span>${formatQuantity(trade.quantity)}</span>
            </div>
        `;
    }).join('');
}

// 퍼센트로 수량 계산
function calculateQuantityByPercent(percent) {
    const price = currentOrderType === 'limit'
        ? parseFloat(document.getElementById('order-price').value) || currentPrices[selectedCode]
        : currentPrices[selectedCode];

    if (!price) return;

    let quantity;
    if (currentSide === 'buy') {
        // 매수: 잔고의 percent%
        const availableKrw = balance * (percent / 100);
        quantity = availableKrw / price;
    } else {
        // 매도: 보유량의 percent%
        const position = positions.find(p => p.code === selectedCode);
        if (position) {
            quantity = position.quantity * (percent / 100);
        } else {
            quantity = 0;
        }
    }

    document.getElementById('order-quantity').value = quantity.toFixed(8);
    updateOrderSummary();
}

// 주문 요약 업데이트
function updateOrderSummary() {
    const quantity = parseFloat(document.getElementById('order-quantity').value) || 0;
    const price = currentOrderType === 'limit'
        ? parseFloat(document.getElementById('order-price').value) || 0
        : currentPrices[selectedCode] || 0;

    const total = quantity * price;
    const fee = total * 0.0005;

    document.getElementById('order-total').textContent = formatNumber(total) + ' KRW';
    document.getElementById('order-fee').textContent = formatNumber(fee) + ' KRW';

    // 버튼 활성화
    const submitBtn = document.getElementById('submit-order');
    const canSubmit = quantity > 0 && price > 0;
    submitBtn.disabled = !canSubmit;
}

// 주문 버튼 업데이트
function updateOrderButton() {
    const btn = document.getElementById('submit-order');
    btn.className = `submit-btn ${currentSide}`;
    btn.textContent = currentSide === 'buy' ? '매수' : '매도';
}

// 주문 제출
async function submitOrder() {
    const quantity = parseFloat(document.getElementById('order-quantity').value);
    const price = currentOrderType === 'limit'
        ? parseFloat(document.getElementById('order-price').value)
        : null;
    const currentPrice = currentPrices[selectedCode];

    if (!quantity || quantity <= 0) {
        alert('수량을 입력하세요.');
        return;
    }

    if (currentOrderType === 'limit' && (!price || price <= 0)) {
        alert('가격을 입력하세요.');
        return;
    }

    if (!currentPrice) {
        alert('시세를 불러오는 중입니다. 잠시 후 다시 시도하세요.');
        return;
    }

    try {
        let order;
        if (currentOrderType === 'market') {
            order = await tradingAPI.createMarketOrder(selectedCode, currentSide, quantity, currentPrice);
        } else {
            order = await tradingAPI.createLimitOrder(selectedCode, currentSide, quantity, price, currentPrice);
        }

        console.log('Order created:', order);
        alert(`${currentSide === 'buy' ? '매수' : '매도'} 주문이 ${order.status === 'filled' ? '체결' : '접수'}되었습니다.`);

        // 입력 초기화
        document.getElementById('order-quantity').value = '';
        document.getElementById('order-price').value = '';
        updateOrderSummary();

        // 데이터 새로고침
        await Promise.all([
            loadBalance(),
            loadPositions(),
            loadOrders(),
            loadTrades()
        ]);

    } catch (error) {
        alert('주문 실패: ' + error.message);
    }
}

// 주문 취소
async function cancelOrder(orderId) {
    if (!confirm('이 주문을 취소하시겠습니까?')) return;

    try {
        await tradingAPI.cancelOrder(orderId);
        alert('주문이 취소되었습니다.');

        await Promise.all([
            loadBalance(),
            loadOrders()
        ]);
    } catch (error) {
        alert('취소 실패: ' + error.message);
    }
}

// 숫자 포맷
function formatNumber(num) {
    if (num === null || num === undefined) return '-';
    return Math.round(num).toLocaleString('ko-KR');
}

function formatQuantity(num) {
    if (num === null || num === undefined) return '-';
    if (num >= 1) return num.toFixed(4);
    return num.toFixed(8);
}

// 차트 초기화
function initChart() {
    const container = document.getElementById('chart-container');
    if (!container) return;

    chart = LightweightCharts.createChart(container, {
        width: container.clientWidth,
        height: container.clientHeight || 400,
        layout: {
            background: { type: 'solid', color: '#0f0f0f' },
            textColor: '#888',
        },
        grid: {
            vertLines: { color: '#222' },
            horzLines: { color: '#222' },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
        },
        rightPriceScale: {
            borderColor: '#333',
        },
        timeScale: {
            borderColor: '#333',
            timeVisible: true,
            secondsVisible: false,
        },
    });

    // 캔들 시리즈
    candleSeries = chart.addCandlestickSeries({
        upColor: '#ef5350',
        downColor: '#26a69a',
        borderUpColor: '#ef5350',
        borderDownColor: '#26a69a',
        wickUpColor: '#ef5350',
        wickDownColor: '#26a69a',
    });

    // 거래량 시리즈 (하단 20% 영역 사용)
    volumeSeries = chart.addHistogramSeries({
        color: '#26a69a',
        priceFormat: {
            type: 'volume',
        },
        priceScaleId: 'volume',
    });

    // 거래량 스케일 설정
    chart.priceScale('volume').applyOptions({
        scaleMargins: {
            top: 0.8,   // 상단 80%는 캔들용
            bottom: 0,  // 하단 20%는 거래량용
        },
        borderVisible: false,
    });

    // Crosshair 이동 시 OHLCV 표시
    chart.subscribeCrosshairMove((param) => {
        if (!param || !param.time || param.point === undefined) {
            // 마우스가 차트 밖으로 나가면 현재 캔들 정보 표시
            updateOhlcvDisplay();
            return;
        }

        // 해당 시간의 캔들 데이터 조회
        const candle = candleDataMap[param.time];
        const volume = volumeDataMap[param.time];

        if (candle) {
            updateOhlcvDisplayWithData(candle, volume || 0);
        }
    });

    // 리사이즈 핸들러
    window.addEventListener('resize', () => {
        chart.applyOptions({
            width: container.clientWidth,
            height: container.clientHeight || 400
        });
    });
}

// 캔들 데이터 로드
async function loadCandles() {
    if (!chart) return;

    try {
        const response = await fetch(`/candles/${selectedCode}?interval=1m&limit=200`);
        const candles = await response.json();

        if (!candles || candles.length === 0) {
            console.log('No candle data');
            return;
        }

        // 시간순 정렬 (오래된 것부터)
        candles.reverse();

        // 데이터 맵 초기화
        candleDataMap = {};
        volumeDataMap = {};

        // 캔들 데이터 변환
        const candleData = candles.map(c => {
            const time = Math.floor(new Date(c.time).getTime() / 1000);
            const candle = {
                time: time,
                open: c.open,
                high: c.high,
                low: c.low,
                close: c.close,
            };
            candleDataMap[time] = candle;
            volumeDataMap[time] = c.volume;
            return candle;
        });

        // 거래량 데이터 변환
        const volumeData = candles.map(c => ({
            time: Math.floor(new Date(c.time).getTime() / 1000),
            value: c.volume,
            color: c.close >= c.open ? 'rgba(239, 83, 80, 0.5)' : 'rgba(38, 166, 154, 0.5)',
        }));

        candleSeries.setData(candleData);
        volumeSeries.setData(volumeData);

        // 마지막 캔들과 거래량 저장
        if (candleData.length > 0) {
            lastCandle = { ...candleData[candleData.length - 1] };
            const lastVolumeData = candles[candles.length - 1];
            lastVolume = lastVolumeData ? lastVolumeData.volume : 0;
            // OHLCV 정보 업데이트
            updateOhlcvDisplay();
        }

        chart.timeScale().fitContent();

    } catch (error) {
        console.error('Failed to load candles:', error);
    }
}

// 차트 실시간 업데이트
function updateChartRealtime(data) {
    if (!candleSeries || !lastCandle) return;

    const price = data.trade_price;
    const volume = data.trade_volume || 0;

    // 현재 시간의 1분 캔들 시작 시간 계산
    const now = Math.floor(Date.now() / 1000);
    const candleTime = now - (now % 60);

    // 같은 캔들이면 업데이트, 새 캔들이면 생성
    if (lastCandle.time === candleTime) {
        // 기존 캔들 업데이트
        lastCandle.high = Math.max(lastCandle.high, price);
        lastCandle.low = Math.min(lastCandle.low, price);
        lastCandle.close = price;
        // 거래량 누적
        lastVolume += volume;
    } else {
        // 새 캔들 생성
        lastCandle = {
            time: candleTime,
            open: price,
            high: price,
            low: price,
            close: price,
        };
        // 새 캔들이므로 거래량 초기화
        lastVolume = volume;
    }

    // 데이터 맵 업데이트
    candleDataMap[candleTime] = { ...lastCandle };
    volumeDataMap[candleTime] = lastVolume;

    // 차트에 반영
    candleSeries.update(lastCandle);

    // 거래량 업데이트 (누적된 값)
    volumeSeries.update({
        time: candleTime,
        value: lastVolume,
        color: lastCandle.close >= lastCandle.open ? 'rgba(239, 83, 80, 0.5)' : 'rgba(38, 166, 154, 0.5)',
    });

    // OHLCV 정보 업데이트
    updateOhlcvDisplay();
}

// OHLCV 정보 표시 업데이트 (현재 캔들)
function updateOhlcvDisplay() {
    if (!lastCandle) return;
    updateOhlcvDisplayWithData(lastCandle, lastVolume);
}

// OHLCV 정보 표시 (특정 데이터로)
function updateOhlcvDisplayWithData(candle, volume) {
    const openEl = document.getElementById('ohlcv-open');
    const highEl = document.getElementById('ohlcv-high');
    const lowEl = document.getElementById('ohlcv-low');
    const closeEl = document.getElementById('ohlcv-close');
    const volumeEl = document.getElementById('ohlcv-volume');

    if (openEl) openEl.textContent = formatNumber(candle.open);
    if (highEl) highEl.textContent = formatNumber(candle.high);
    if (lowEl) lowEl.textContent = formatNumber(candle.low);
    if (closeEl) {
        closeEl.textContent = formatNumber(candle.close);
        // 종가 색상: 시가 대비 상승/하락
        closeEl.className = 'ohlcv-value ' + (candle.close >= candle.open ? 'up' : 'down');
    }
    if (volumeEl) volumeEl.textContent = formatVolumeCompact(volume);
}

// 거래량 포맷 (축약형)
function formatVolumeCompact(vol) {
    if (vol === null || vol === undefined) return '-';
    if (vol >= 1000000) return (vol / 1000000).toFixed(2) + 'M';
    if (vol >= 1000) return (vol / 1000).toFixed(2) + 'K';
    return vol.toFixed(4);
}
