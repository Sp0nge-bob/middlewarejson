"""Credential-free diagnostics for bearer subscription requests."""
import hashlib
import hmac
import logging
import secrets

# An ephemeral process key permits correlation without publishing a token hash.
# Restart intentionally breaks correlation; no production secret is required.
_CORRELATION_KEY = secrets.token_bytes(32)


def subscription_log_id(sub_id: str) -> str:
    return hmac.new(_CORRELATION_KEY, sub_id.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


class _TransportFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == "uvicorn.access":
            # Uvicorn's access args contain the complete bearer path and query.
            record.msg = "HTTP access event"
        elif record.name == "httpx" or record.name.startswith("httpcore"):
            # HTTPX logs full URLs; httpcore DEBUG can expose protocol metadata.
            record.msg = "HTTP transport event"
        else:
            return True
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


_FILTER = _TransportFilter()


def configure_safe_transport_logging() -> None:
    # Logger filters cover standard HTTPX/Uvicorn handlers and log captures.
    # Root handler filters additionally cover propagated httpcore child loggers.
    for name in ("httpx", "uvicorn.access", "httpcore", "httpcore.connection",
                 "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks"):
        logging.getLogger(name).addFilter(_FILTER)
    for handler in logging.getLogger().handlers:
        handler.addFilter(_FILTER)
