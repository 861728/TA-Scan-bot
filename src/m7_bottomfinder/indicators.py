from __future__ import annotations

from dataclasses import dataclass
from math import isnan

from .data_layer import Bar, normalize_timestamp
from .divergence import DivergenceDetector, DivergenceType
from .indicator_engine import BaseIndicator, IndicatorResult, SignalDirection


def _last(values: list[float], default: float = 0.0) -> float:
    return values[-1] if values else default


def _sma(values: list[float], period: int) -> list[float]:
    out: list[float] = []
    for i in range(len(values)):
        if i + 1 < period:
            out.append(float("nan"))
        else:
            chunk = values[i - period + 1 : i + 1]
            out.append(sum(chunk) / period)
    return out


def _ema(values: list[float], period: int) -> list[float]:
    out: list[float] = []
    if not values:
        return out
    k = 2 / (period + 1)
    prev = values[0]
    out.append(prev)
    for v in values[1:]:
        prev = (v * k) + (prev * (1 - k))
        out.append(prev)
    return out


def _rsi(closes: list[float], period: int = 14) -> list[float]:
    if len(closes) < 2:
        return [50.0 for _ in closes]
    gains = [0.0]
    losses = [0.0]
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(abs(min(d, 0.0)))
    avg_gain = _sma(gains, period)
    avg_loss = _sma(losses, period)
    out: list[float] = []
    for g, l in zip(avg_gain, avg_loss):
        if isnan(g) or isnan(l):
            out.append(50.0)
        elif l == 0:
            out.append(100.0)
        else:
            rs = g / l
            out.append(100 - (100 / (1 + rs)))
    return out


def _stochastic(values: list[float], period: int = 14) -> list[float]:
    out: list[float] = []
    for i in range(len(values)):
        if i + 1 < period:
            out.append(50.0)
            continue
        chunk = values[i - period + 1 : i + 1]
        lo = min(chunk)
        hi = max(chunk)
        if hi == lo:
            out.append(50.0)
        else:
            out.append((values[i] - lo) / (hi - lo) * 100)
    return out


def _obv(bars: list[Bar]) -> list[float]:
    if not bars:
        return []
    out = [0.0]
    for i in range(1, len(bars)):
        if bars[i].close > bars[i - 1].close:
            out.append(out[-1] + bars[i].volume)
        elif bars[i].close < bars[i - 1].close:
            out.append(out[-1] - bars[i].volume)
        else:
            out.append(out[-1])
    return out


def _ad_line(bars: list[Bar]) -> list[float]:
    out: list[float] = []
    total = 0.0
    for b in bars:
        hl = b.high - b.low
        mfm = 0.0 if hl == 0 else ((b.close - b.low) - (b.high - b.close)) / hl
        total += mfm * b.volume
        out.append(total)
    return out


def _mfi(bars: list[Bar], period: int = 14) -> list[float]:
    typical = [(b.high + b.low + b.close) / 3 for b in bars]
    pos = [0.0]
    neg = [0.0]
    for i in range(1, len(bars)):
        flow = typical[i] * bars[i].volume
        if typical[i] > typical[i - 1]:
            pos.append(flow)
            neg.append(0.0)
        elif typical[i] < typical[i - 1]:
            pos.append(0.0)
            neg.append(flow)
        else:
            pos.append(0.0)
            neg.append(0.0)
    pos_sum = _sma(pos, period)
    neg_sum = _sma(neg, period)
    out: list[float] = []
    for p, n in zip(pos_sum, neg_sum):
        if isnan(p) or isnan(n):
            out.append(50.0)
        elif n == 0:
            out.append(100.0)
        else:
            ratio = p / n
            out.append(100 - (100 / (1 + ratio)))
    return out


def _cmf(bars: list[Bar], period: int = 20) -> list[float]:
    mfv: list[float] = []
    vol: list[float] = []
    for b in bars:
        hl = b.high - b.low
        mfm = 0.0 if hl == 0 else ((b.close - b.low) - (b.high - b.close)) / hl
        mfv.append(mfm * b.volume)
        vol.append(b.volume)
    out: list[float] = []
    for i in range(len(bars)):
        if i + 1 < period:
            out.append(0.0)
        else:
            m = sum(mfv[i - period + 1 : i + 1])
            v = sum(vol[i - period + 1 : i + 1])
            out.append(0.0 if v == 0 else m / v)
    return out


def _std(values: list[float]) -> float:
    if not values:
        return 0.0
    m = sum(values) / len(values)
    var = sum((x - m) ** 2 for x in values) / len(values)
    return var ** 0.5


def _macd(closes: list[float]) -> tuple[list[float], list[float], list[float]]:
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    line = [a - b for a, b in zip(ema12, ema26)]
    signal = _ema(line, 9)
    hist = [a - b for a, b in zip(line, signal)]
    return line, signal, hist


class WVFIndicator(BaseIndicator):
    name = "wvf_spike"
    weight = 3

    def __init__(self, lookback: int = 22, threshold: float = 80.0) -> None:
        self.lookback = lookback
        self.threshold = threshold

    def _evaluate(self, bars: list[Bar]) -> IndicatorResult:
        closes = [b.close for b in bars]
        lows = [b.low for b in bars]
        if len(bars) < self.lookback:
            return IndicatorResult.neutral(self.name, bars[-1].timestamp, "insufficient data")
        highest = max(closes[-self.lookback :])
        wvf = ((highest - lows[-1]) / highest) * 100 if highest else 0.0
        bullish = wvf >= self.threshold
        return IndicatorResult(
            indicator=self.name,
            signal=SignalDirection.BULLISH if bullish else SignalDirection.NEUTRAL,
            score=self.weight if bullish else 0,
            evidence=f"wvf={wvf:.2f} threshold={self.threshold}",
            raw_values={"wvf": wvf, "threshold": self.threshold},
            timestamp=normalize_timestamp(bars[-1].timestamp),
        )


class VolumeCapitulationIndicator(BaseIndicator):
    name = "volume_capitulation"
    weight = 3

    def __init__(self, period: int = 20, multiple: float = 3.0) -> None:
        self.period = period
        self.multiple = multiple

    def _evaluate(self, bars: list[Bar]) -> IndicatorResult:
        vols = [b.volume for b in bars]
        if len(vols) < self.period:
            return IndicatorResult.neutral(self.name, bars[-1].timestamp, "insufficient data")
        avg = sum(vols[-self.period :]) / self.period
        spike = vols[-1] >= avg * self.multiple if avg else False
        return IndicatorResult(
            indicator=self.name,
            signal=SignalDirection.BULLISH if spike else SignalDirection.NEUTRAL,
            score=self.weight if spike else 0,
            evidence=f"volume={vols[-1]:.2f} avg={avg:.2f} multiple={self.multiple}",
            raw_values={"volume": vols[-1], "avg": avg, "multiple": self.multiple},
            timestamp=normalize_timestamp(bars[-1].timestamp),
        )


class OBVDivergenceIndicator(BaseIndicator):
    name = "obv_divergence"
    weight = 3

    def __init__(self, pivot_window: int = 1) -> None:
        self.detector = DivergenceDetector(pivot_window=pivot_window)

    def _evaluate(self, bars: list[Bar]) -> IndicatorResult:
        closes = [b.close for b in bars]
        obv = _obv(bars)
        signal = self.detector.detect(closes, obv, [b.timestamp for b in bars])
        bull = signal.found and signal.kind == DivergenceType.BULLISH
        return IndicatorResult(
            indicator=self.name,
            signal=SignalDirection.BULLISH if bull else SignalDirection.NEUTRAL,
            score=self.weight if bull else 0,
            evidence=signal.evidence,
            raw_values={"found": signal.found, "kind": signal.kind.value},
            timestamp=normalize_timestamp(bars[-1].timestamp),
        )


class MFIIndicator(BaseIndicator):
    name = "mfi"
    weight = 1

    def __init__(self, oversold: float = 20.0) -> None:
        self.oversold = oversold

    def _evaluate(self, bars: list[Bar]) -> IndicatorResult:
        m = _mfi(bars)
        last = _last(m, 50.0)
        bull = last <= self.oversold
        return IndicatorResult(
            self.name,
            SignalDirection.BULLISH if bull else SignalDirection.NEUTRAL,
            self.weight if bull else 0,
            f"mfi={last:.2f} oversold={self.oversold}",
            {"mfi": last, "oversold": self.oversold},
            normalize_timestamp(bars[-1].timestamp),
        )


class CMFIndicator(BaseIndicator):
    name = "cmf"
    weight = 1

    def _evaluate(self, bars: list[Bar]) -> IndicatorResult:
        c = _cmf(bars)
        last = _last(c, 0.0)
        bull = last > 0
        return IndicatorResult(
            self.name,
            SignalDirection.BULLISH if bull else SignalDirection.NEUTRAL,
            self.weight if bull else 0,
            f"cmf={last:.4f}",
            {"cmf": last},
            normalize_timestamp(bars[-1].timestamp),
        )


class TripleStochRSIIndicator(BaseIndicator):
    name = "triple_stoch_rsi"
    weight = 1

    def _evaluate(self, bars: list[Bar]) -> IndicatorResult:
        closes = [b.close for b in bars]
        r = _rsi(closes, 14)
        s1 = _stochastic(r, 14)
        s2 = _stochastic(r, 21)
        s3 = _stochastic(r, 28)
        v1, v2, v3 = _last(s1, 50), _last(s2, 50), _last(s3, 50)
        bull = v1 < 20 and v2 < 20 and v3 < 20
        return IndicatorResult(
            self.name,
            SignalDirection.BULLISH if bull else SignalDirection.NEUTRAL,
            self.weight if bull else 0,
            f"stoch_rsi=({v1:.1f},{v2:.1f},{v3:.1f})",
            {"s1": v1, "s2": v2, "s3": v3},
            normalize_timestamp(bars[-1].timestamp),
        )


class ADLineDivergenceIndicator(BaseIndicator):
    name = "adline_divergence"
    weight = 1

    def __init__(self, pivot_window: int = 1) -> None:
        self.detector = DivergenceDetector(pivot_window=pivot_window)

    def _evaluate(self, bars: list[Bar]) -> IndicatorResult:
        closes = [b.close for b in bars]
        ad = _ad_line(bars)
        signal = self.detector.detect(closes, ad, [b.timestamp for b in bars])
        bull = signal.found and signal.kind == DivergenceType.BULLISH
        return IndicatorResult(
            self.name,
            SignalDirection.BULLISH if bull else SignalDirection.NEUTRAL,
            self.weight if bull else 0,
            signal.evidence,
            {"found": signal.found, "kind": signal.kind.value},
            normalize_timestamp(bars[-1].timestamp),
        )


class CompositeOscillatorIndicator(BaseIndicator):
    name = "composite_oscillator"
    weight = 1

    def _evaluate(self, bars: list[Bar]) -> IndicatorResult:
        closes = [b.close for b in bars]
        r = _last(_rsi(closes), 50)
        k = _last(_stochastic(closes), 50)
        comp = (r + k) / 2
        bull = comp < 30
        return IndicatorResult(self.name, SignalDirection.BULLISH if bull else SignalDirection.NEUTRAL, self.weight if bull else 0, f"composite={comp:.2f}", {"composite": comp}, normalize_timestamp(bars[-1].timestamp))


class VPTIndicator(BaseIndicator):
    name = "vpt"
    weight = 1

    def _evaluate(self, bars: list[Bar]) -> IndicatorResult:
        vpt = [0.0]
        for i in range(1, len(bars)):
            prev = bars[i - 1].close
            change = 0.0 if prev == 0 else (bars[i].close - prev) / prev
            vpt.append(vpt[-1] + (bars[i].volume * change))
        trend_up = len(vpt) >= 3 and vpt[-1] > vpt[-2] > vpt[-3]
        return IndicatorResult(self.name, SignalDirection.BULLISH if trend_up else SignalDirection.NEUTRAL, self.weight if trend_up else 0, f"vpt_last={_last(vpt):.2f}", {"vpt": _last(vpt)}, normalize_timestamp(bars[-1].timestamp))


class NVIPVIIndicator(BaseIndicator):
    name = "nvi_pvi"
    weight = 1

    def _evaluate(self, bars: list[Bar]) -> IndicatorResult:
        nvi = [1000.0]
        pvi = [1000.0]
        for i in range(1, len(bars)):
            prev_close = bars[i - 1].close
            change = 0.0 if prev_close == 0 else (bars[i].close - prev_close) / prev_close
            if bars[i].volume < bars[i - 1].volume:
                nvi.append(nvi[-1] * (1 + change))
            else:
                nvi.append(nvi[-1])
            if bars[i].volume > bars[i - 1].volume:
                pvi.append(pvi[-1] * (1 + change))
            else:
                pvi.append(pvi[-1])
        bull = nvi[-1] > _sma(nvi, 20)[-1] if len(nvi) >= 20 else False
        return IndicatorResult(self.name, SignalDirection.BULLISH if bull else SignalDirection.NEUTRAL, self.weight if bull else 0, f"nvi={nvi[-1]:.2f} pvi={pvi[-1]:.2f}", {"nvi": nvi[-1], "pvi": pvi[-1]}, normalize_timestamp(bars[-1].timestamp))


class RSISMA200Indicator(BaseIndicator):
    name = "rsi_sma200"
    weight = 1

    def _evaluate(self, bars: list[Bar]) -> IndicatorResult:
        closes = [b.close for b in bars]
        r = _last(_rsi(closes), 50)
        sma200 = _last(_sma(closes, 200), closes[-1])
        bull = r < 30 and closes[-1] >= sma200
        return IndicatorResult(self.name, SignalDirection.BULLISH if bull else SignalDirection.NEUTRAL, self.weight if bull else 0, f"rsi={r:.2f} close={closes[-1]:.2f} sma200={sma200:.2f}", {"rsi": r, "close": closes[-1], "sma200": sma200}, normalize_timestamp(bars[-1].timestamp))


class BBStochasticIndicator(BaseIndicator):
    name = "bb_stochastic"
    weight = 1

    def _evaluate(self, bars: list[Bar]) -> IndicatorResult:
        closes = [b.close for b in bars]
        sma20 = _last(_sma(closes, 20), closes[-1])
        std20 = _std(closes[-20:]) if len(closes) >= 20 else 0.0
        lower = sma20 - (2 * std20)
        stoch = _last(_stochastic(closes, 14), 50)
        bull = closes[-1] <= lower and stoch > 20
        return IndicatorResult(self.name, SignalDirection.BULLISH if bull else SignalDirection.NEUTRAL, self.weight if bull else 0, f"close={closes[-1]:.2f} lower={lower:.2f} stoch={stoch:.2f}", {"close": closes[-1], "lower": lower, "stoch": stoch}, normalize_timestamp(bars[-1].timestamp))


class MACDOBVDivergenceIndicator(BaseIndicator):
    name = "macd_obv_divergence"
    weight = 1

    def __init__(self, pivot_window: int = 1) -> None:
        self.detector = DivergenceDetector(pivot_window=pivot_window)

    def _evaluate(self, bars: list[Bar]) -> IndicatorResult:
        closes = [b.close for b in bars]
        macd_line, _, _ = _macd(closes)
        obv = _obv(bars)
        sig1 = self.detector.detect(closes, macd_line, [b.timestamp for b in bars])
        sig2 = self.detector.detect(closes, obv, [b.timestamp for b in bars])
        bull = (sig1.found and sig1.kind == DivergenceType.BULLISH) and (sig2.found and sig2.kind == DivergenceType.BULLISH)
        return IndicatorResult(self.name, SignalDirection.BULLISH if bull else SignalDirection.NEUTRAL, self.weight if bull else 0, f"macd={sig1.kind.value} obv={sig2.kind.value}", {"macd_kind": sig1.kind.value, "obv_kind": sig2.kind.value}, normalize_timestamp(bars[-1].timestamp))


class FibonacciSupportIndicator(BaseIndicator):
    name = "fibonacci_618_support"
    weight = 1

    def __init__(self, lookback: int = 60, tolerance: float = 0.01) -> None:
        self.lookback = lookback
        self.tolerance = tolerance

    def _evaluate(self, bars: list[Bar]) -> IndicatorResult:
        closes = [b.close for b in bars]
        chunk = closes[-self.lookback :] if len(closes) >= self.lookback else closes
        hi, lo = max(chunk), min(chunk)
        level = hi - (hi - lo) * 0.618
        near = abs(closes[-1] - level) / level <= self.tolerance if level else False
        return IndicatorResult(self.name, SignalDirection.BULLISH if near else SignalDirection.NEUTRAL, self.weight if near else 0, f"close={closes[-1]:.2f} fib618={level:.2f}", {"close": closes[-1], "fib618": level}, normalize_timestamp(bars[-1].timestamp))


class IchimokuRSIOBVIndicator(BaseIndicator):
    name = "ichimoku_rsi_obv"
    weight = 1

    def _evaluate(self, bars: list[Bar]) -> IndicatorResult:
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        closes = [b.close for b in bars]
        if len(bars) < 52:
            return IndicatorResult.neutral(self.name, bars[-1].timestamp, "insufficient data")
        tenkan = (max(highs[-9:]) + min(lows[-9:])) / 2
        kijun = (max(highs[-26:]) + min(lows[-26:])) / 2
        span_b = (max(highs[-52:]) + min(lows[-52:])) / 2
        span_a = (tenkan + kijun) / 2
        r = _last(_rsi(closes), 50)
        obv = _obv(bars)
        bull = closes[-1] >= max(span_a, span_b) and r > 45 and obv[-1] > obv[-2]
        return IndicatorResult(self.name, SignalDirection.BULLISH if bull else SignalDirection.NEUTRAL, self.weight if bull else 0, f"close={closes[-1]:.2f} cloud=({span_a:.2f},{span_b:.2f}) rsi={r:.2f}", {"close": closes[-1], "span_a": span_a, "span_b": span_b, "rsi": r}, normalize_timestamp(bars[-1].timestamp))


class KsReversalIndicator(BaseIndicator):
    name = "ks_reversal"
    weight = 1

    def _evaluate(self, bars: list[Bar]) -> IndicatorResult:
        closes = [b.close for b in bars]
        ema8 = _last(_ema(closes, 8), closes[-1])
        ema21 = _last(_ema(closes, 21), closes[-1])
        r = _last(_rsi(closes), 50)
        bull = ema8 > ema21 and r > 40
        return IndicatorResult(self.name, SignalDirection.BULLISH if bull else SignalDirection.NEUTRAL, self.weight if bull else 0, f"ema8={ema8:.2f} ema21={ema21:.2f} rsi={r:.2f}", {"ema8": ema8, "ema21": ema21, "rsi": r}, normalize_timestamp(bars[-1].timestamp))


class MACDDivergenceIndicator(BaseIndicator):
    name = "macd_divergence"
    weight = 1

    def __init__(self, pivot_window: int = 1) -> None:
        self.detector = DivergenceDetector(pivot_window=pivot_window)

    def _evaluate(self, bars: list[Bar]) -> IndicatorResult:
        closes = [b.close for b in bars]
        line, _, _ = _macd(closes)
        signal = self.detector.detect(closes, line, [b.timestamp for b in bars])
        bull = signal.found and signal.kind == DivergenceType.BULLISH
        return IndicatorResult(self.name, SignalDirection.BULLISH if bull else SignalDirection.NEUTRAL, self.weight if bull else 0, signal.evidence, {"kind": signal.kind.value}, normalize_timestamp(bars[-1].timestamp))


def default_phase2_indicators() -> list[BaseIndicator]:
    return [
        WVFIndicator(),
        VolumeCapitulationIndicator(),
        OBVDivergenceIndicator(),
        MFIIndicator(),
        CMFIndicator(),
        TripleStochRSIIndicator(),
        ADLineDivergenceIndicator(),
        CompositeOscillatorIndicator(),
        VPTIndicator(),
        NVIPVIIndicator(),
        RSISMA200Indicator(),
        BBStochasticIndicator(),
        MACDOBVDivergenceIndicator(),
        FibonacciSupportIndicator(),
        IchimokuRSIOBVIndicator(),
        KsReversalIndicator(),
        MACDDivergenceIndicator(),
    ]
