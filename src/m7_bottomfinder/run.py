from __future__ import annotations

from pathlib import Path

from .app import ScanAppConfig, ScanApplication
from .data_layer import Bar


def default_fetcher(_symbol: str, _timeframe: str) -> list[Bar]:
    # Provider integration point (e.g., yfinance). Return empty to trigger cache fallback.
    return []


def main() -> None:
    config_path = Path("config.toml")
    if not config_path.exists():
        config_path = Path("config.example.toml")

    config = ScanAppConfig.from_toml(config_path)
    app = ScanApplication(config)
    app.run_forever(default_fetcher)


if __name__ == "__main__":
    main()
