# M7-BottomFinder

M7 종목의 바닥권(공포 매도 소진 + 자금 유입)을 수치형 기술지표로 스캔하고, 조건 충족 시 텔레그램 알림/AI 해석을 제공하는 프로젝트입니다.

## 확정 운영 파라미터

- **티커(M7):** `AAPL`, `MSFT`, `GOOG`, `AMZN`, `NVDA`, `META`, `TSLA`
- **메인 트리거 타임프레임:** `15m`
- **HTF 필터:** `1h`, `1d`
- **알람 최소 점수:** `5`
- **AI 해석 호출 점수:** `6`
- **AI 호출 추가 조건:** S등급 지표 2개 이상
- **동일 종목/동일 방향 쿨타임:** `120분`
- **쿨타임 예외:** 2시간 이내라도 직전 대비 점수 +3 이상이면 강화 신호 즉시 발송
- **AI 호출 제한:** 종목당 일일 3회, 봇 전체 일일 20회
- **장중 기준:** 정규장/프리장 구분 없이 조건 충족 시 동작

## 지표 등급/점수

### S등급 (각 3점)
- WVF Spike
- Volume Capitulation Spike
- OBV Divergence

### A등급 (각 1점)
- MFI
- CMF
- Triple Stoch RSI
- MACD Divergence
- 기타 수치형 보조지표

## 알림/AI 로직

1. 총점 `>=5`면 텔레그램 기본 템플릿 알림 발송
2. 총점 `>=6` 또는 S등급 2개 이상이면 GPT-4o 정밀 해석 호출
3. 동일 종목/동일 방향은 120분 쿨타임 적용
4. 단, 스코어가 직전 알림 대비 +3 이상이면 쿨타임 무시하고 강화 신호 발송

## 백테스트/KPI 기준

- **기간:** 최근 12개월(기본안: 2025-02 ~ 2026-02)
- **Precision 목표:** 70% 이상
  - 정의: 알람 후 5거래일 내 +3% 이상 반등 비율
- **MDD 목표:** -5% 이내
- **평균 반등폭 목표:** +5% 이상
- **신호 지속성:** 평균 2~3일
- **추가 지표:** Signal-to-Noise Ratio, Time to Recovery

## 개발 단계(업데이트)

- **Phase 1:** 인프라/캐시/환율/텔레그램
- **Phase 1.5:** 백테스트 시뮬레이터(과거 알람 생성 + KPI 산출)
- **Phase 2:** 15개 수치지표 및 다이버전스 엔진
- **Phase 3:** AI 브레인/쿨타임/예외복구
- **Phase 4:** Systemd 운영/무중단 배포/최종 검수

## Step A 구현 상태 (데이터 레이어 고정)

현재 코드 기준으로 아래 4가지를 우선 완료했습니다.

- **캐시 스키마 고정:** `schema_version`, `symbol`, `timeframe`, `timezone(UTC)`, `bars[]` 구조의 JSON 파일 캐시
- **증분 병합 로직:** 동일 타임스탬프 충돌 시 최신 수신 바 우선(덮어쓰기) + 시간순 정렬
- **결측 보정:** 짧은 홀(기본 60분 이하)에 대해 carry-forward 바(거래량 0) 자동 삽입
- **타임존 통일:** 입력이 KST/naive/UTC여도 저장 시 UTC로 정규화

구현 모듈:
- `src/m7_bottomfinder/data_layer.py`
- `tests/test_data_layer.py`


## Step B/C 구현 상태 (Phase 2 지표 라이브러리 + 다이버전스 엔진)

Phase 2 개발을 위해 지표 공통 인터페이스와 재사용 가능한 다이버전스 엔진을 추가했습니다.

- 공통 인터페이스: `IndicatorResult(signal, score, evidence, raw_values)`, `IndicatorEngine`
- 다이버전스 엔진: `DivergenceDetector` (price/indicator 피벗 기반 bullish/bearish 판정)
- 지표 구현(수치 기반): WVF, Volume Capitulation, OBV Divergence, MFI, CMF, Triple Stoch RSI, A/D Divergence, Composite Oscillator, VPT, NVI/PVI, RSI+SMA200, BB+Stoch, MACD+OBV Divergence, Fibonacci 61.8, Ichimoku+RSI+OBV, K's Reversal, MACD Divergence

구현 모듈:
- `src/m7_bottomfinder/indicator_engine.py`
- `src/m7_bottomfinder/divergence.py`
- `src/m7_bottomfinder/indicators.py`
- `tests/test_phase2_indicators.py`


## Step 1.5 구현 상태 (백테스트 시뮬레이터 + KPI 산출)

Phase 1.5 요구사항에 맞춰 과거 바 데이터 기반 시뮬레이터를 추가했습니다.

- `BacktestSimulator`: 바 단위로 지표 엔진을 재평가해 가상 알람 시점 생성
- 쿨타임/강화 신호 반영: `cooldown_bars`, `strengthen_delta`
- KPI 산출: Precision, Avg Rebound, Max Drawdown, Signal Duration, Signal-to-Noise Ratio, Time to Recovery
- `summarize_kpi`: 리포트 직렬화용 요약 dict 제공

구현 모듈:
- `src/m7_bottomfinder/backtest.py`
- `tests/test_backtest_simulator.py`


## Step 3 구현 상태 (알림 엔진 + AI 브레인 + 예외복구)

Phase 3 핵심 모듈을 추가했습니다.

- `AlertEngine`: 심볼/방향 단위 쿨타임 + 강화 신호(+3) 예외 + 중복 억제
- `AIInterpreter`: `should_send` + `should_call_ai` 동시 충족 시에만 AI 해석 수행
- `AIUsageLimiter`: 종목/전체 일일 호출 제한
- `FetchRecovery`: 데이터 제공자 오류 시 캐시 fallback 복구

구현 모듈:
- `src/m7_bottomfinder/alert_engine.py`
- `src/m7_bottomfinder/ai_layer.py`
- `src/m7_bottomfinder/recovery.py`
- `tests/test_alert_ai_recovery.py`


## Step 4 구현 상태 (운영 런타임 오케스트레이션)

운영 단계(Phase 4) 진입을 위해 스캔 파이프라인 오케스트레이터를 추가했습니다.


운영 배포 보강:

- `YahooFinanceFetcher`/`TelegramNotifier` 연동 포인트 추가 (실데이터/실알림 연결)
- `ScanApplication`/`run.py` 엔트리포인트 추가 (`config.toml` 기반 실행)
- `deploy/m7-bottomfinder.service` systemd 템플릿 추가

- `ScannerRuntime.run_cycle`: fetch/recovery -> cache update -> indicator scoring -> alert gating -> AI call -> notify 순서 실행
- `ScanRuntimeConfig`: 심볼/타임프레임/결측 보정 파라미터 관리
- `ScanCycleResult`: 사이클 결과(알림 액션, AI 호출 여부, 데이터 소스) 반환
- `Notifier` 프로토콜: 텔레그램/슬랙 등 전송기 교체 가능 구조

구현 모듈:
- `src/m7_bottomfinder/runtime.py`
- `src/m7_bottomfinder/app.py`
- `src/m7_bottomfinder/run.py`
- `src/m7_bottomfinder/providers.py`
- `src/m7_bottomfinder/notifiers.py`
- `deploy/m7-bottomfinder.service`
- `tests/test_runtime.py`
- `tests/test_app.py`
