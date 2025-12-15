import logging
import os
import socket
import urllib.request

HEALTHCHECK_PING_URL = os.getenv("HEALTHCHECK_PING_URL")

logger = logging.getLogger(__name__)


def ping_healthcheck():
    if HEALTHCHECK_PING_URL:
        try:
            urllib.request.urlopen(HEALTHCHECK_PING_URL, timeout=10)
        except socket.error as e:
            # Log ping failure here...
            logger.error(f"Healthcheck ping failed: {e}")
    else:
        logger.warning("HEALTHCHECK_PING_URL not set; skipping healthcheck ping.")
