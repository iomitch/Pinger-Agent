import asyncio
import logging
import signal
import sys

from agent.client import AgentClient
from agent.config import settings
from agent.scheduler import AgentScheduler


def main() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger("agent")

    if not settings.pinger_api_key:
        logger.error("PINGER_API_KEY is not set. Exiting.")
        sys.exit(1)

    logger.info("Starting Pinger Agent")
    logger.info("Server: %s", settings.pinger_server_url)

    client = AgentClient()
    scheduler = AgentScheduler(client)

    loop = asyncio.new_event_loop()

    def _shutdown(sig: signal.Signals) -> None:
        logger.info("Received %s, shutting down...", sig.name)
        scheduler.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown, sig)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            signal.signal(sig, lambda s, f: _shutdown(signal.Signals(s)))

    try:
        loop.run_until_complete(scheduler.run())
    except KeyboardInterrupt:
        scheduler.stop()
    finally:
        loop.run_until_complete(client.close())
        loop.close()
        logger.info("Agent stopped.")


if __name__ == "__main__":
    main()
