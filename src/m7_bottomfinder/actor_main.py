"""Apify Actor entrypoint for M7 BottomFinder."""
from __future__ import annotations

import asyncio
from pathlib import Path

from apify import Actor


async def main() -> None:
    async with Actor:
        actor_input = await Actor.get_input() or {}
        mode = actor_input.get("mode", "scan")

        Actor.log.info(f"Starting M7 BottomFinder in '{mode}' mode")

        from .app import ScanAppConfig, ScanApplication
        from .notifiers import SafeNotifier, TelegramNotifier
        from .providers import YahooFinanceFetcher

        config_path = Path("config.toml")
        if not config_path.exists():
            config_path = Path("config.example.toml")

        config = ScanAppConfig.from_toml(config_path)

        notifier = None
        if config.telegram_bot_token and config.telegram_chat_id:
            notifier = SafeNotifier(TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id))

        app = ScanApplication(config, notifier=notifier)
        fetcher = YahooFinanceFetcher()

        if mode == "forever":
            Actor.log.info("Running in scheduled loop mode")
            app.run_forever(fetcher)
        else:
            Actor.log.info("Running single scan cycle")
            alerted = app.run_once(fetcher)
            Actor.log.info(f"Scan complete. Alerted symbols: {alerted}")

            await Actor.push_data({
                "status": "completed",
                "alerted_symbols": alerted,
                "mode": mode,
            })


if __name__ == "__main__":
    asyncio.run(main())
