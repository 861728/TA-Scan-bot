#!/bin/bash
# us_trading_bot 파일을 861728/us-trading-bot 레포로 마이그레이션
# VPS에서 실행: bash migrate_to_new_repo.sh

set -e

WORK_DIR="/tmp/us-trading-bot-migrate"
SOURCE_REPO="https://github.com/861728/TA-Scan-bot.git"
SOURCE_BRANCH="claude/us-trading-bot-JVB3z"
TARGET_REPO="https://github.com/861728/us-trading-bot.git"

echo "=== 1. 소스 클론 ==="
rm -rf "$WORK_DIR"
mkdir -p "$WORK_DIR"
git clone --branch "$SOURCE_BRANCH" --single-branch "$SOURCE_REPO" "$WORK_DIR/source"

echo "=== 2. 새 레포 구성 ==="
mkdir -p "$WORK_DIR/target/us_trading_bot"
mkdir -p "$WORK_DIR/target/tests"

# 소스 파일 복사
cp "$WORK_DIR/source/us_trading_bot/__init__.py"    "$WORK_DIR/target/us_trading_bot/"
cp "$WORK_DIR/source/us_trading_bot/config.py"      "$WORK_DIR/target/us_trading_bot/"
cp "$WORK_DIR/source/us_trading_bot/database.py"    "$WORK_DIR/target/us_trading_bot/"
cp "$WORK_DIR/source/us_trading_bot/indicators.py"  "$WORK_DIR/target/us_trading_bot/"
cp "$WORK_DIR/source/us_trading_bot/scanner.py"     "$WORK_DIR/target/us_trading_bot/"
cp "$WORK_DIR/source/us_trading_bot/notifier.py"    "$WORK_DIR/target/us_trading_bot/"
cp "$WORK_DIR/source/us_trading_bot/scheduler.py"   "$WORK_DIR/target/us_trading_bot/"

# requirements.txt → 프로젝트 루트
cp "$WORK_DIR/source/us_trading_bot/requirements.txt" "$WORK_DIR/target/"

# 테스트 파일 복사
cp "$WORK_DIR/source/tests/conftest.py"          "$WORK_DIR/target/tests/"
cp "$WORK_DIR/source/tests/test_config.py"       "$WORK_DIR/target/tests/"
cp "$WORK_DIR/source/tests/test_database.py"     "$WORK_DIR/target/tests/"
cp "$WORK_DIR/source/tests/test_indicators.py"   "$WORK_DIR/target/tests/"
cp "$WORK_DIR/source/tests/test_scanner.py"      "$WORK_DIR/target/tests/"
cp "$WORK_DIR/source/tests/test_notifier.py"     "$WORK_DIR/target/tests/"
cp "$WORK_DIR/source/tests/test_scheduler.py"    "$WORK_DIR/target/tests/"

# .gitignore 생성
cat > "$WORK_DIR/target/.gitignore" << 'GITIGNORE'
venv/
__pycache__/
*.pyc
trades.db
*.log
.env
GITIGNORE

echo "=== 3. 파일 구조 확인 ==="
find "$WORK_DIR/target" -type f | sort

echo ""
echo "=== 4. git init + push ==="
cd "$WORK_DIR/target"
git init
git add .
git commit -m "initial commit: us trading bot"
git branch -M main
git remote add origin "$TARGET_REPO"
git push -u origin main

echo ""
echo "=== 완료! ==="
echo "https://github.com/861728/us-trading-bot"

# 정리
rm -rf "$WORK_DIR"
