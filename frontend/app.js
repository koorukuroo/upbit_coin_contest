// 상태 관리
let ws = null;
let chart = null;
let candleSeries = null;
let volumeSeries = null;
let selectedCode = 'KRW-BTC';
let selectedInterval = '1m';
let tickerData = {};

// 차트 설정
let isPercentMode = false;
let isLogScale = false;
let rawCandleData = []; // 원본 캔들 데이터 저장

// 통계
let tickCount = 0;
let ticksPerSecond = 0;
let ticksInLastSecond = 0;
const MAX_TRADES = 100; // 테이블에 보여줄 최대 거래 수

// API 기본 URL
const API_BASE = window.location.origin;
const WS_PROTOCOL = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const WS_URL = `${WS_PROTOCOL}//${window.location.host}/ws`;

// 초기화
document.addEventListener('DOMContentLoaded', () => {
    initChart();
    connectWebSocket();
    loadCandles();
    updateTime();
    setupEventListeners();

    // 1초마다 시간 및 TPS 업데이트
    setInterval(() => {
        updateTime();
        updateTPS();
    }, 1000);

    // 30초마다 캔들 새로고침
    setInterval(loadCandles, 30000);
});

// 현재 시간 업데이트
function updateTime() {
    const now = new Date();
    const timeStr = now.toLocaleString('ko-KR', {
        timeZone: 'Asia/Seoul',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
    document.getElementById('current-time').textContent = timeStr;
}

// TPS 업데이트
function updateTPS() {
    ticksPerSecond = ticksInLastSecond;
    ticksInLastSecond = 0;
    document.getElementById('tps').textContent = ticksPerSecond;
}

// WebSocket 연결
function connectWebSocket() {
    console.log('Connecting to WebSocket:', WS_URL);
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
        console.log('WebSocket connected');
        document.getElementById('connection-status').textContent = 'Connected';
        document.getElementById('connection-status').className = 'connected';

        // 전체 코인 구독
        ws.send(JSON.stringify({ subscribe: 'all' }));
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);

        // 구독 확인 메시지 무시
        if (data.status === 'subscribed') {
            console.log('Subscribed:', data);
            return;
        }

        // 통계 업데이트
        tickCount++;
        ticksInLastSecond++;
        document.getElementById('tick-count').textContent = tickCount.toLocaleString();

        // 티커 데이터 업데이트
        updateTickerBoard(data);

        // 거래 내역 테이블에 추가
        addTradeRow(data);
    };

    ws.onclose = () => {
        console.log('WebSocket disconnected');
        document.getElementById('connection-status').textContent = 'Disconnected';
        document.getElementById('connection-status').className = 'disconnected';

        // 3초 후 재연결
        setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
    };
}

// 티커 보드 업데이트
function updateTickerBoard(data) {
    const code = data.code;
    const card = document.querySelector(`.ticker-card[data-code="${code}"]`);

    if (!card) return;

    const priceEl = card.querySelector('.ticker-price');
    const changeEl = card.querySelector('.ticker-change');

    // 가격 포맷팅
    const price = data.trade_price;
    const change = data.signed_change_rate * 100;
    const changeType = data.change;

    // 이전 가격과 비교하여 플래시 효과
    if (tickerData[code] && tickerData[code].price !== price) {
        const direction = price > tickerData[code].price ? 'rise' : 'fall';
        card.classList.remove('flash-rise', 'flash-fall');
        void card.offsetWidth; // 리플로우 트리거
        card.classList.add(`flash-${direction}`);
    }

    // 데이터 저장
    tickerData[code] = { price, change, changeType };

    // 가격 표시
    priceEl.textContent = formatPrice(price);

    // 변동률 표시
    const changeText = change >= 0 ? `+${change.toFixed(2)}%` : `${change.toFixed(2)}%`;
    changeEl.textContent = changeText;
    changeEl.className = 'ticker-change';

    if (changeType === 'RISE') {
        changeEl.classList.add('rise');
    } else if (changeType === 'FALL') {
        changeEl.classList.add('fall');
    } else {
        changeEl.classList.add('even');
    }
}

// 거래 내역 테이블에 추가
function addTradeRow(data) {
    const tbody = document.getElementById('trades-body');

    // 새 행 생성
    const row = document.createElement('tr');
    row.className = 'new-row';

    // 시간 포맷
    const timestamp = data.trade_timestamp || Date.now();
    const time = new Date(timestamp);
    const timeStr = time.toLocaleTimeString('ko-KR', {
        timeZone: 'Asia/Seoul',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        fractionalSecondDigits: 3
    });

    // 변동률
    const changeRate = (data.signed_change_rate * 100);
    const changeClass = data.change === 'RISE' ? 'rise' : (data.change === 'FALL' ? 'fall' : '');
    const changeText = changeRate >= 0 ? `+${changeRate.toFixed(2)}%` : `${changeRate.toFixed(2)}%`;

    // 매수/매도
    const side = data.ask_bid;
    const sideClass = side === 'ASK' ? 'ask' : 'bid';
    const sideText = side === 'ASK' ? '매도' : '매수';

    // 코인명 (KRW- 제거)
    const coinName = data.code.replace('KRW-', '');

    row.innerHTML = `
        <td class="trade-time">${timeStr}</td>
        <td class="trade-code">${coinName}</td>
        <td class="trade-price ${changeClass}">${formatPriceFull(data.trade_price)}</td>
        <td class="trade-volume">${data.trade_volume.toFixed(4)}</td>
        <td class="trade-change ${changeClass}">${changeText}</td>
        <td><span class="trade-side ${sideClass}">${sideText}</span></td>
    `;

    // 맨 위에 추가
    tbody.insertBefore(row, tbody.firstChild);

    // 애니메이션 후 클래스 제거
    setTimeout(() => row.classList.remove('new-row'), 500);

    // 최대 개수 유지
    while (tbody.children.length > MAX_TRADES) {
        tbody.removeChild(tbody.lastChild);
    }
}

// 가격 포맷팅 (축약)
function formatPrice(price) {
    if (price >= 1000000) {
        return (price / 1000000).toFixed(2) + 'M';
    } else if (price >= 1000) {
        return price.toLocaleString('ko-KR');
    } else if (price >= 1) {
        return price.toFixed(2);
    } else {
        return price.toFixed(4);
    }
}

// 가격 포맷팅 (전체)
function formatPriceFull(price) {
    if (price >= 1000) {
        return price.toLocaleString('ko-KR');
    } else if (price >= 1) {
        return price.toFixed(2);
    } else {
        return price.toFixed(4);
    }
}

// 차트 초기화
function initChart() {
    const container = document.getElementById('chart-container');

    chart = LightweightCharts.createChart(container, {
        width: container.clientWidth,
        height: 400,
        layout: {
            background: { type: 'solid', color: '#16213e' },
            textColor: '#aaa',
        },
        grid: {
            vertLines: { color: '#1f3460' },
            horzLines: { color: '#1f3460' },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
        },
        rightPriceScale: {
            borderColor: '#1f3460',
        },
        timeScale: {
            borderColor: '#1f3460',
            timeVisible: true,
            secondsVisible: false,
        },
    });

    // 캔들 시리즈
    candleSeries = chart.addCandlestickSeries({
        upColor: '#d63031',
        downColor: '#0984e3',
        borderUpColor: '#d63031',
        borderDownColor: '#0984e3',
        wickUpColor: '#d63031',
        wickDownColor: '#0984e3',
    });

    // 거래량 시리즈
    volumeSeries = chart.addHistogramSeries({
        color: '#26a69a',
        priceFormat: {
            type: 'volume',
        },
        priceScaleId: '',
        scaleMargins: {
            top: 0.8,
            bottom: 0,
        },
    });

    // 리사이즈 핸들러
    window.addEventListener('resize', () => {
        chart.applyOptions({ width: container.clientWidth });
    });
}

// 캔들 데이터 로드
async function loadCandles() {
    try {
        const response = await fetch(
            `${API_BASE}/candles/${selectedCode}?interval=${selectedInterval}&limit=200`
        );
        const candles = await response.json();

        if (!candles || candles.length === 0) {
            console.log('No candle data');
            return;
        }

        // 시간순 정렬 (오래된 것부터)
        candles.reverse();

        // 원본 데이터 저장
        rawCandleData = candles;

        // 차트 데이터 적용
        applyChartData();

        // 요약 통계 업데이트
        updateSummary(candles);

        // 차트 맞춤
        chart.timeScale().fitContent();

    } catch (error) {
        console.error('Failed to load candles:', error);
    }
}

// 차트 데이터 적용 (퍼센트 모드 지원)
function applyChartData() {
    if (!rawCandleData || rawCandleData.length === 0) return;

    let candleData;
    const basePrice = rawCandleData[0].open; // 기준 가격 (첫 캔들 시가)

    if (isPercentMode) {
        // 퍼센트 모드: 첫 캔들 대비 % 변화로 표시
        candleData = rawCandleData.map(c => ({
            time: parseTime(c.time),
            open: ((c.open - basePrice) / basePrice) * 100,
            high: ((c.high - basePrice) / basePrice) * 100,
            low: ((c.low - basePrice) / basePrice) * 100,
            close: ((c.close - basePrice) / basePrice) * 100,
        }));
    } else {
        // 일반 모드
        candleData = rawCandleData.map(c => ({
            time: parseTime(c.time),
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close,
        }));
    }

    // 거래량 데이터 변환
    const volumeData = rawCandleData.map(c => ({
        time: parseTime(c.time),
        value: c.volume,
        color: c.close >= c.open ? 'rgba(214, 48, 49, 0.5)' : 'rgba(9, 132, 227, 0.5)',
    }));

    candleSeries.setData(candleData);
    volumeSeries.setData(volumeData);
}

// 시간 파싱 (UTC timestamp로 변환)
function parseTime(timeStr) {
    const date = new Date(timeStr);
    return Math.floor(date.getTime() / 1000);
}

// 요약 통계 업데이트
function updateSummary(candles) {
    if (!candles || candles.length === 0) return;

    const first = candles[0];
    const last = candles[candles.length - 1];

    const open = first.open;
    const close = last.close;
    const high = Math.max(...candles.map(c => c.high));
    const low = Math.min(...candles.map(c => c.low));
    const totalVolume = candles.reduce((sum, c) => sum + c.volume, 0);
    const changeRate = ((close - open) / open * 100);

    document.getElementById('summary-code').textContent = `(${selectedCode})`;
    document.getElementById('summary-open').textContent = formatPrice(open);
    document.getElementById('summary-high').textContent = formatPrice(high);
    document.getElementById('summary-low').textContent = formatPrice(low);
    document.getElementById('summary-close').textContent = formatPrice(close);
    document.getElementById('summary-volume').textContent = totalVolume.toFixed(4);

    const changeEl = document.getElementById('summary-change');
    changeEl.textContent = (changeRate >= 0 ? '+' : '') + changeRate.toFixed(2) + '%';
    changeEl.className = 'summary-value';
    if (changeRate > 0) {
        changeEl.classList.add('rise');
    } else if (changeRate < 0) {
        changeEl.classList.add('fall');
    }
}

// 이벤트 리스너 설정
function setupEventListeners() {
    // 티커 카드 클릭
    document.querySelectorAll('.ticker-card').forEach(card => {
        card.addEventListener('click', () => {
            // 선택 상태 업데이트
            document.querySelectorAll('.ticker-card').forEach(c => c.classList.remove('selected'));
            card.classList.add('selected');

            // 선택된 코인 변경
            selectedCode = card.dataset.code;
            document.getElementById('coin-select').value = selectedCode;

            // 캔들 새로고침
            loadCandles();
        });
    });

    // 코인 선택 드롭다운
    document.getElementById('coin-select').addEventListener('change', (e) => {
        selectedCode = e.target.value;

        // 티커 카드 선택 상태 업데이트
        document.querySelectorAll('.ticker-card').forEach(card => {
            card.classList.toggle('selected', card.dataset.code === selectedCode);
        });

        loadCandles();
    });

    // 시간 간격 버튼
    document.querySelectorAll('.interval-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.interval-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            selectedInterval = btn.dataset.interval;
            loadCandles();
        });
    });

    // 초기 선택 상태
    document.querySelector(`.ticker-card[data-code="${selectedCode}"]`)?.classList.add('selected');

    // 차트 도구 버튼
    document.getElementById('btn-fit').addEventListener('click', () => {
        chart.timeScale().fitContent();
    });

    document.getElementById('btn-reset').addEventListener('click', () => {
        chart.timeScale().resetTimeScale();
        chart.priceScale('right').applyOptions({ autoScale: true });
        chart.timeScale().fitContent();
    });

    document.getElementById('btn-percent').addEventListener('click', (e) => {
        isPercentMode = !isPercentMode;
        e.target.closest('.tool-btn').classList.toggle('active', isPercentMode);

        // 가격 스케일 포맷 변경
        candleSeries.applyOptions({
            priceFormat: isPercentMode
                ? { type: 'percent', precision: 2, minMove: 0.01 }
                : { type: 'price', precision: 0, minMove: 1 }
        });

        applyChartData();
        chart.timeScale().fitContent();
    });

    document.getElementById('btn-log').addEventListener('click', (e) => {
        isLogScale = !isLogScale;
        e.target.closest('.tool-btn').classList.toggle('active', isLogScale);

        chart.priceScale('right').applyOptions({
            mode: isLogScale ? 1 : 0  // 1 = logarithmic, 0 = normal
        });
    });
}
