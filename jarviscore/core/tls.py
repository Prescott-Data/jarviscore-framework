"""Shared TLS context factory.

Every outbound HTTPS connection in the framework verifies certificates.
The only way to disable verification is the JARVISCORE_TLS_INSECURE
environment variable, which exists for corporate-proxy debugging and
logs a prominent warning each time it is used.
"""

import logging
import os
import ssl

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}


def create_ssl_context() -> ssl.SSLContext:
    """Return a verifying SSL context backed by the certifi CA bundle.

    Falls back to the system trust store when certifi is unavailable.
    Verification stays on in both cases. Set JARVISCORE_TLS_INSECURE=1
    to disable verification entirely; a warning is logged because this
    exposes traffic (including auth headers) to interception.
    """
    if os.environ.get("JARVISCORE_TLS_INSECURE", "").strip().lower() in _TRUTHY:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        logger.warning(
            "TLS certificate verification DISABLED via JARVISCORE_TLS_INSECURE. "
            "Traffic is exposed to interception. Never use this in production."
        )
        return ctx

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()
