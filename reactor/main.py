"""REACTOR — Entry point. Creates coordinator, registers workers, starts API."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from .api import start_server
from .coordinator import Coordinator
from .workers.api_pool import APIPoolWorker
from .workers.kaggle_worker import KaggleWorker
from .workers.modal_worker import ModalWorker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("reactor.main")


async def main() -> None:
    """Initialize and run REACTOR."""
    logger.info("⚡ REACTOR v1.0 — GPU Task Coordinator starting...")

    # Create coordinator
    coordinator = Coordinator(max_concurrent=3)

    # Register workers
    # Modal GPU workers
    modal_a100 = ModalWorker(gpu_type="A100")
    modal_t4 = ModalWorker(gpu_type="T4")
    coordinator.register_worker("modal_a100", modal_a100)
    coordinator.register_worker("modal_t4", modal_t4)

    # Kaggle worker
    kaggle = KaggleWorker()
    coordinator.register_worker("kaggle_t4x2", kaggle)

    # API pool workers (each specialized for their source)
    api_pollinations = APIPoolWorker(preferred_source="pollinations")
    api_agnes = APIPoolWorker(preferred_source="agnes")
    api_huggingface = APIPoolWorker(preferred_source="huggingface")
    coordinator.register_worker("api_pollinations", api_pollinations)
    coordinator.register_worker("api_agnes", api_agnes)
    coordinator.register_worker("api_huggingface", api_huggingface)

    # Start API server
    runner = await start_server(coordinator)

    # Start coordinator loop
    coordinator_task = asyncio.create_task(coordinator.run())

    logger.info("⚡ REACTOR fully operational")

    # Handle shutdown
    stop_event = asyncio.Event()

    def _signal_handler():
        logger.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    # Wait for shutdown
    await stop_event.wait()

    # Cleanup
    await coordinator.stop()
    coordinator_task.cancel()
    await runner.cleanup()
    logger.info("⚡ REACTOR shutdown complete")


def run() -> None:
    """Sync entry point."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted")
        sys.exit(0)


if __name__ == "__main__":
    run()
