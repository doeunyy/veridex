"""Class-only framework error records at Uvicorn's error handler boundary.

Uvicorn logs ASGI and lifespan failures with full tracebacks. A traceback prints raw
exception messages, including chained __cause__/__context__ text that may carry
provider or request details. Such records are rewritten in place to one event with
an allowlisted exception class; lifecycle, warning and access records are unchanged.
"""

import copy
import json
import logging

from uvicorn.config import LOGGING_CONFIG

from veridex.observability import exception_class

_CLASSIFICATIONS = {
    "Exception in ASGI application\n": "asgi_application",
    "Exception in 'lifespan' protocol\n": "lifespan_protocol",
}
# Fixed Uvicorn messages with no interpolated or exception-derived text.
_SAFE_ERRORS = {
    "Application startup failed. Exiting.",
    "Application shutdown failed. Exiting.",
    "ASGI callable returned without starting response.",
    "ASGI callable returned without completing response.",
}
_TRACEBACK = "Traceback (most recent call last)"
_FALLBACK = json.dumps({"classification": "unclassified", "event": "framework_error"})


def _exception(record):
    if isinstance(record.exc_info, tuple) and isinstance(record.exc_info[1], BaseException):
        return record.exc_info[1]
    if isinstance(record.msg, BaseException):
        return record.msg
    args = record.args if isinstance(record.args, tuple) else (record.args,)
    return next((arg for arg in args if isinstance(arg, BaseException)), None)


def _classify(message):
    if not isinstance(message, str):
        return "unclassified"
    if message in _CLASSIFICATIONS:
        return _CLASSIFICATIONS[message]
    return "traceback_text" if _TRACEBACK in message else "unclassified"


class SanitizedFrameworkErrors(logging.Filter):
    """Never drops a record and never formats exception objects or record arguments."""

    def filter(self, record):
        try:
            exception = _exception(record)
            if exception is None and (
                record.levelno < logging.ERROR
                or (isinstance(record.msg, str) and record.msg in _SAFE_ERRORS and not record.args)
            ):
                return True
            event = {"classification": _classify(record.msg), "event": "framework_error"}
            if exception is not None:
                event["exception_class"] = exception_class(exception)
            message = json.dumps(event, sort_keys=True)
        except Exception:  # noqa: BLE001 — a malformed record must still be redacted
            message = _FALLBACK
        record.msg = message
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


def uvicorn_log_config():
    """Uvicorn's default config with the filter on the handler serving uvicorn.error."""
    config = copy.deepcopy(LOGGING_CONFIG)
    config.setdefault("filters", {})["sanitized_framework_errors"] = {
        "()": SanitizedFrameworkErrors
    }
    config["handlers"]["default"].setdefault("filters", []).append("sanitized_framework_errors")
    return config
