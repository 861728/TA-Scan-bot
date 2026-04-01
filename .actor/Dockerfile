FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/
COPY config.example.toml .

RUN pip install --no-cache-dir -e ".[all]" \
    && pip install --no-cache-dir apify anthropic requests yfinance

CMD ["python", "-m", "m7_bottomfinder.actor_main"]
