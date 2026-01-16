#!/usr/bin/env python3
"""
간단한 백테스팅 시뮬레이터
ClickHouse에 저장된 시세 데이터로 투자 전략을 테스트합니다.
"""
import sys
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Optional, Callable
from abc import ABC, abstractmethod
import clickhouse_connect

# ClickHouse 설정
CH_HOST = "localhost"
CH_PORT = 8123
CH_USER = "default"
CH_PASSWORD = "clickhousepw"
CH_DATABASE = "default"

# 거래 설정
COMMISSION_RATE = 0.0005  # 업비트 수수료 0.05%


@dataclass
class Candle:
    """캔들 데이터"""
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Trade:
    """거래 기록"""
    time: datetime
    side: str  # "buy" or "sell"
    price: float
    quantity: float
    commission: float
    pnl: float = 0  # 매도 시 손익


@dataclass
class Position:
    """포지션"""
    quantity: float = 0
    avg_price: float = 0

    def update_buy(self, price: float, quantity: float):
        total_cost = self.avg_price * self.quantity + price * quantity
        self.quantity += quantity
        self.avg_price = total_cost / self.quantity if self.quantity > 0 else 0

    def update_sell(self, quantity: float) -> float:
        self.quantity -= quantity
        if self.quantity <= 0:
            self.quantity = 0
            self.avg_price = 0
        return self.quantity


@dataclass
class BacktestResult:
    """백테스트 결과"""
    initial_capital: float
    final_capital: float
    total_return: float
    total_return_pct: float
    max_drawdown: float
    max_drawdown_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    trades: List[Trade]
    equity_curve: List[tuple]


class Strategy(ABC):
    """전략 베이스 클래스"""

    def __init__(self):
        self.candles: List[Candle] = []

    def add_candle(self, candle: Candle):
        self.candles.append(candle)

    @abstractmethod
    def signal(self) -> Optional[str]:
        """
        현재 캔들에서 신호 생성
        Returns: "buy", "sell", or None
        """
        pass

    def sma(self, period: int) -> Optional[float]:
        """단순 이동평균"""
        if len(self.candles) < period:
            return None
        closes = [c.close for c in self.candles[-period:]]
        return sum(closes) / period

    def ema(self, period: int) -> Optional[float]:
        """지수 이동평균"""
        if len(self.candles) < period:
            return None
        multiplier = 2 / (period + 1)
        ema = self.candles[-period].close
        for candle in self.candles[-period+1:]:
            ema = (candle.close - ema) * multiplier + ema
        return ema

    def rsi(self, period: int = 14) -> Optional[float]:
        """RSI"""
        if len(self.candles) < period + 1:
            return None

        gains, losses = [], []
        for i in range(-period, 0):
            change = self.candles[i].close - self.candles[i-1].close
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))

        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def bollinger_bands(self, period: int = 20, std_dev: float = 2) -> Optional[tuple]:
        """볼린저 밴드 (middle, upper, lower)"""
        if len(self.candles) < period:
            return None

        closes = [c.close for c in self.candles[-period:]]
        middle = sum(closes) / period
        variance = sum((c - middle) ** 2 for c in closes) / period
        std = variance ** 0.5

        return (middle, middle + std_dev * std, middle - std_dev * std)


# ============ 예시 전략들 ============

class SMAcrossStrategy(Strategy):
    """이동평균 교차 전략"""

    def __init__(self, short_period: int = 5, long_period: int = 20):
        super().__init__()
        self.short_period = short_period
        self.long_period = long_period
        self.prev_short = None
        self.prev_long = None

    def signal(self) -> Optional[str]:
        short_sma = self.sma(self.short_period)
        long_sma = self.sma(self.long_period)

        if short_sma is None or long_sma is None:
            return None

        signal = None
        if self.prev_short and self.prev_long:
            # 골든 크로스: 단기선이 장기선을 상향 돌파
            if self.prev_short <= self.prev_long and short_sma > long_sma:
                signal = "buy"
            # 데드 크로스: 단기선이 장기선을 하향 돌파
            elif self.prev_short >= self.prev_long and short_sma < long_sma:
                signal = "sell"

        self.prev_short = short_sma
        self.prev_long = long_sma
        return signal


class RSIStrategy(Strategy):
    """RSI 전략"""

    def __init__(self, period: int = 14, oversold: int = 30, overbought: int = 70):
        super().__init__()
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self.prev_rsi = None

    def signal(self) -> Optional[str]:
        current_rsi = self.rsi(self.period)

        if current_rsi is None:
            return None

        signal = None
        if self.prev_rsi:
            # RSI가 과매도에서 벗어날 때 매수
            if self.prev_rsi <= self.oversold and current_rsi > self.oversold:
                signal = "buy"
            # RSI가 과매수에서 벗어날 때 매도
            elif self.prev_rsi >= self.overbought and current_rsi < self.overbought:
                signal = "sell"

        self.prev_rsi = current_rsi
        return signal


class BollingerBandStrategy(Strategy):
    """볼린저 밴드 전략"""

    def __init__(self, period: int = 20, std_dev: float = 2):
        super().__init__()
        self.period = period
        self.std_dev = std_dev

    def signal(self) -> Optional[str]:
        bb = self.bollinger_bands(self.period, self.std_dev)

        if bb is None or len(self.candles) < 2:
            return None

        middle, upper, lower = bb
        prev_close = self.candles[-2].close
        curr_close = self.candles[-1].close

        # 하단 돌파 후 복귀 시 매수
        if prev_close <= lower and curr_close > lower:
            return "buy"
        # 상단 돌파 후 복귀 시 매도
        elif prev_close >= upper and curr_close < upper:
            return "sell"

        return None


# ============ 백테스팅 엔진 ============

class Backtester:
    """백테스팅 엔진"""

    def __init__(
        self,
        code: str,
        strategy: Strategy,
        initial_capital: float = 1_000_000,
        trade_ratio: float = 1.0,  # 자본 대비 거래 비율
        interval: str = "1m"
    ):
        self.code = code
        self.strategy = strategy
        self.initial_capital = initial_capital
        self.trade_ratio = trade_ratio
        self.interval = interval

        self.cash = initial_capital
        self.position = Position()
        self.trades: List[Trade] = []
        self.equity_curve: List[tuple] = []

        self.client = clickhouse_connect.get_client(
            host=CH_HOST, port=CH_PORT,
            username=CH_USER, password=CH_PASSWORD,
            database=CH_DATABASE
        )

    def load_candles(self, start: str, end: str) -> List[Candle]:
        """ClickHouse에서 캔들 데이터 로드"""
        interval_map = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400}
        seconds = interval_map.get(self.interval, 60)

        result = self.client.query(f"""
            SELECT
                toStartOfInterval(timestamp, INTERVAL {seconds} SECOND) as candle_time,
                argMin(trade_price, timestamp) as open,
                max(trade_price) as high,
                min(trade_price) as low,
                argMax(trade_price, timestamp) as close,
                sum(trade_volume) as volume
            FROM upbit_ticker
            WHERE code = '{self.code}'
              AND timestamp >= '{start}'
              AND timestamp <= '{end}'
            GROUP BY candle_time
            ORDER BY candle_time ASC
        """)

        candles = []
        for row in result.result_rows:
            candles.append(Candle(
                time=row[0],
                open=row[1],
                high=row[2],
                low=row[3],
                close=row[4],
                volume=row[5]
            ))
        return candles

    def execute_buy(self, candle: Candle):
        """매수 실행"""
        price = candle.close
        available = self.cash * self.trade_ratio
        commission = available * COMMISSION_RATE
        quantity = (available - commission) / price

        if quantity <= 0:
            return

        self.cash -= available
        self.position.update_buy(price, quantity)

        self.trades.append(Trade(
            time=candle.time,
            side="buy",
            price=price,
            quantity=quantity,
            commission=commission
        ))

    def execute_sell(self, candle: Candle):
        """매도 실행"""
        if self.position.quantity <= 0:
            return

        price = candle.close
        quantity = self.position.quantity
        gross = price * quantity
        commission = gross * COMMISSION_RATE
        net = gross - commission

        # 손익 계산
        cost = self.position.avg_price * quantity
        pnl = net - cost

        self.cash += net
        self.position.update_sell(quantity)

        self.trades.append(Trade(
            time=candle.time,
            side="sell",
            price=price,
            quantity=quantity,
            commission=commission,
            pnl=pnl
        ))

    def get_equity(self, price: float) -> float:
        """현재 총 자산"""
        return self.cash + self.position.quantity * price

    def run(self, start: str, end: str) -> BacktestResult:
        """백테스트 실행"""
        print(f"📊 백테스트 시작: {self.code}")
        print(f"   기간: {start} ~ {end}")
        print(f"   전략: {self.strategy.__class__.__name__}")
        print(f"   초기자본: {self.initial_capital:,.0f}원")
        print()

        candles = self.load_candles(start, end)
        print(f"   캔들 수: {len(candles)}")

        if not candles:
            raise ValueError("캔들 데이터가 없습니다")

        peak_equity = self.initial_capital
        max_drawdown = 0

        for candle in candles:
            self.strategy.add_candle(candle)
            signal = self.strategy.signal()

            if signal == "buy" and self.position.quantity == 0:
                self.execute_buy(candle)
            elif signal == "sell" and self.position.quantity > 0:
                self.execute_sell(candle)

            # 자산 기록
            equity = self.get_equity(candle.close)
            self.equity_curve.append((candle.time, equity))

            # MDD 계산
            if equity > peak_equity:
                peak_equity = equity
            drawdown = peak_equity - equity
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        # 마지막에 포지션 정리
        if self.position.quantity > 0:
            self.execute_sell(candles[-1])

        return self._calculate_result(max_drawdown, peak_equity)

    def _calculate_result(self, max_drawdown: float, peak_equity: float) -> BacktestResult:
        """결과 계산"""
        final_capital = self.cash
        total_return = final_capital - self.initial_capital
        total_return_pct = (total_return / self.initial_capital) * 100
        max_drawdown_pct = (max_drawdown / peak_equity) * 100 if peak_equity > 0 else 0

        # 승률 계산
        sell_trades = [t for t in self.trades if t.side == "sell"]
        winning = [t for t in sell_trades if t.pnl > 0]
        losing = [t for t in sell_trades if t.pnl <= 0]
        win_rate = len(winning) / len(sell_trades) * 100 if sell_trades else 0

        # Profit Factor
        gross_profit = sum(t.pnl for t in winning) if winning else 0
        gross_loss = abs(sum(t.pnl for t in losing)) if losing else 1
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        # Sharpe Ratio (간단 버전)
        if len(self.equity_curve) > 1:
            returns = []
            for i in range(1, len(self.equity_curve)):
                ret = (self.equity_curve[i][1] - self.equity_curve[i-1][1]) / self.equity_curve[i-1][1]
                returns.append(ret)

            if returns:
                avg_return = sum(returns) / len(returns)
                variance = sum((r - avg_return) ** 2 for r in returns) / len(returns)
                std_return = variance ** 0.5
                sharpe_ratio = (avg_return / std_return) * (252 ** 0.5) if std_return > 0 else 0
            else:
                sharpe_ratio = 0
        else:
            sharpe_ratio = 0

        return BacktestResult(
            initial_capital=self.initial_capital,
            final_capital=final_capital,
            total_return=total_return,
            total_return_pct=total_return_pct,
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_drawdown_pct,
            total_trades=len(self.trades),
            winning_trades=len(winning),
            losing_trades=len(losing),
            win_rate=win_rate,
            profit_factor=profit_factor,
            sharpe_ratio=sharpe_ratio,
            trades=self.trades,
            equity_curve=self.equity_curve
        )


def print_result(result: BacktestResult):
    """결과 출력"""
    print()
    print("=" * 60)
    print("📈 백테스트 결과")
    print("=" * 60)
    print(f"  초기자본:     {result.initial_capital:>15,.0f}원")
    print(f"  최종자본:     {result.final_capital:>15,.0f}원")
    print(f"  총 수익:      {result.total_return:>15,.0f}원 ({result.total_return_pct:+.2f}%)")
    print()
    print(f"  최대낙폭(MDD): {result.max_drawdown:>14,.0f}원 ({result.max_drawdown_pct:.2f}%)")
    print(f"  총 거래:      {result.total_trades:>15}회")
    print(f"  승/패:        {result.winning_trades:>7} / {result.losing_trades}")
    print(f"  승률:         {result.win_rate:>14.1f}%")
    print(f"  Profit Factor:{result.profit_factor:>14.2f}")
    print(f"  Sharpe Ratio: {result.sharpe_ratio:>14.2f}")
    print("=" * 60)

    # 최근 거래 내역
    if result.trades:
        print("\n📝 최근 거래 (최대 10건)")
        print("-" * 60)
        for trade in result.trades[-10:]:
            pnl_str = f" (PnL: {trade.pnl:+,.0f})" if trade.side == "sell" else ""
            print(f"  {trade.time} | {trade.side:4} | {trade.price:>12,.0f} | {trade.quantity:.6f}{pnl_str}")


def main():
    """메인 함수"""
    # 기본 설정
    code = "KRW-BTC"
    start = "2026-01-07 00:00:00"
    end = "2026-01-12 00:00:00"
    initial_capital = 1_000_000

    # 명령행 인자 처리
    if len(sys.argv) > 1:
        code = sys.argv[1]
    if len(sys.argv) > 2:
        start = sys.argv[2]
    if len(sys.argv) > 3:
        end = sys.argv[3]

    print("=" * 60)
    print("🎯 투자 시뮬레이션")
    print("=" * 60)
    print()
    print("사용 가능한 전략:")
    print("  1. SMA 교차 (5일/20일)")
    print("  2. RSI (14일, 30/70)")
    print("  3. 볼린저 밴드 (20일)")
    print()

    choice = input("전략 선택 (1-3, 기본값 1): ").strip() or "1"

    if choice == "1":
        strategy = SMAcrossStrategy(short_period=5, long_period=20)
    elif choice == "2":
        strategy = RSIStrategy(period=14, oversold=30, overbought=70)
    elif choice == "3":
        strategy = BollingerBandStrategy(period=20, std_dev=2)
    else:
        strategy = SMAcrossStrategy()

    # 백테스트 실행
    backtester = Backtester(
        code=code,
        strategy=strategy,
        initial_capital=initial_capital,
        trade_ratio=0.95,  # 자본의 95% 사용
        interval="5m"  # 5분봉
    )

    result = backtester.run(start, end)
    print_result(result)


if __name__ == "__main__":
    main()
