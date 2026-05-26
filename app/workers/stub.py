"""Placeholder worker process — replaced by procrastinate worker in Issue #9."""
import logging
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logger.info("Worker stub running. Replace CMD with procrastinate worker in Issue #9.")
    while True:
        time.sleep(60)
