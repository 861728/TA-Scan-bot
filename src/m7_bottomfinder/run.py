from __future__ import annotations

from pathlib import Path

from .app import ScanAppConfig, ScanApplication
from .notifiers import SafeNotifier, TelegramNotifier
from .providers import YahooFinanceFetcher


def main() -> None:
    config_path = Path("config.toml")
    if not config_path.exists():
        config_path = Path("config.example.toml")

    config = ScanAppConfig.from_toml(config_path)

    notifier = None
    if config.telegram_bot_token and config.telegram_chat_id:
        notifier = SafeNotifier(TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id))

    app = ScanApplication(config, notifier=notifier)
    app.run_forever(YahooFinanceFetcher())


if __name__ == "__main__":
    main()
