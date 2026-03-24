# M7-BottomFinder 프로젝트 컨텍스트

## 프로젝트 개요
나스닥 기술주 바닥/눌림목을 스캔해서 텔레그램으로 매수 신호를 보내는 봇.
VPS(DigitalOcean, Singapore)에서 systemd로 운영 중. Python + yfinance 기반.
매일 07:00 KST 자동 스캔 및 발송.

## 역할 분담
- **Claude.ai 채팅**: 방향 결정, 디렉션 작성, 개념 설명
- **Claude Code (여기)**: 실제 코드 수정, 커밋, 푸시
- **VPS**: 실제 실행 (`/opt/m7-bottomfinder`)

## 브랜치 규칙
- main 직접 푸시 불가 (403)
- `claude/` 브랜치로 푸시 → PR 머지 → GitHub Actions 자동 배포

## 주요 파일 구조
```
src/m7_bottomfinder/
├── app.py               # 설정 로드, 스케줄러, run_once() 흐름
├── runtime.py           # 스캔 파이프라인
├── indicators.py        # calculate_score() / calculate_track2_score()
├── indicator_engine.py  # 트랙 판별, 점수 집계
├── alert_engine.py      # 쿨타임, 중복 판단
├── trade_store.py       # SQLite 매수 기록 (trades.db)
├── telegram_handler.py  # polling 명령어 수신 (/buy, /positions)
├── notifiers.py         # 텔레그램 발송 (urllib만 사용)
├── providers.py         # yfinance 데이터 fetcher, KRW 환율
config.example.toml      # 운영 파라미터 예시 (실제는 VPS에서 관리)
```

## 전략 구조

### 트랙 1 ⚡고수익 - 바닥 반등
- 종목: NVDA, MRVL, CRWD, ZS, ON
- 목표: +20%, 30일 홀딩, 손절 없음
- threshold: 4+
- 조건: RSI 30이하(+1), 200MA 아래(+1), 60일 고점대비 -20%+(+1), CMF 유입(+1), OBV 다이버전스(+1), 거래량 급증(+1) → 최대 6점

### 트랙 2 🛡️안전 - 눌림목 매수
- 종목: MU, LRCX, NFLX, KLAC
- 목표: +10%, 30일 홀딩, 손절 없음
- threshold: 5+
- 조건: 200MA 위(+2), 20MA 아래(+1), RSI 38~48(+1), 고점대비 -12~20%(+1), 거래량 감소(+1) → 최대 6점

## 알람 구조 (매일 07:00 KST)

### ① 매도 D-7 알람 (해당 포지션 있을 때만)
```
⏰ NVDA 매도 D-7 $176.21 → $192.50 (+9.2%) | 매도일 2026-04-07
```

### ② 일일 요약 (무조건 1건)
```
📅 2026-03-24 스캔 결과
━━━━━━━━━━━━━━━
⚡ 신호
• NVDA ⚡고수익 (5점) | $176.21 | +20% | 30일

💼 보유 포지션
• NVDA ⚡ | $176.21 → $192.50 | +9.2% | D+15
```

## 텔레그램 명령어
- `/buy NVDA 176.21` → 매수 기록 저장
- `/positions` → 보유 포지션 조회

## VPS 운영
- 경로: `/opt/m7-bottomfinder`
- 서비스: systemd (`m7-bottomfinder.service`)
- `config.toml`: gitignore (VPS에서 직접 관리)
- `trades.db`: gitignore (VPS 로컬 SQLite)
- 배포: GitHub Actions (main 머지 시 자동)

## config.toml 주요 항목
```toml
[runtime]
symbols = ["NVDA", "MRVL", "CRWD", "ZS", "ON", "MU", "LRCX", "NFLX", "KLAC"]
timeframe = "1d"
interval_seconds = 86400

[scoring]
track1_threshold = 4
track2_threshold = 5
track1_symbols = ["NVDA", "MRVL", "CRWD", "ZS", "ON"]
track2_symbols = ["MU", "LRCX", "NFLX", "KLAC"]

[telegram]
db_path = "/opt/m7-bottomfinder/trades.db"
```

## 작업 시 주의사항
- `score_threshold` 참조 전 grep으로 확인: `grep -r "score_threshold" .`
- 트랙 1, 트랙 2 score 함수 분리 유지
- urllib만 사용 (외부 텔레그램 라이브러리 추가 금지)
- 🔴/🟢 사용 금지 → ⚡/🛡️ 로 통일
