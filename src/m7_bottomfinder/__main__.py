"""Allow running as `python -m m7_bottomfinder`."""
import asyncio

from m7_bottomfinder.actor_main import main

asyncio.run(main())
