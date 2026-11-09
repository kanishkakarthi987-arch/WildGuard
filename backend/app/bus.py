"""A change counter that the live stream (/api/stream) watches.

Every database write bumps it, so the dashboard can refresh the moment a camera, collar or
sensor reports instead of waiting for the next poll. In-process only: with several uvicorn
workers, run one worker or put a real pub/sub (Redis) here.
"""

import threading

_lock = threading.Lock()
_version = 0


def bump() -> int:
    global _version
    with _lock:
        _version += 1
        return _version


def version() -> int:
    return _version
