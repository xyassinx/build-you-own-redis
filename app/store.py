"""In-memory key/value store with optional per-key expiration.

Values are kept as raw bytes. Expiration uses lazy eviction: an expired key is
removed the next time it is accessed (or when listing keys). This is the same
simple approach the CodeCrafters challenge expects.
"""

import time


class Store:
    def __init__(self):
        self._data = {}     # key -> value
        self._expires = {}  # key -> absolute expiration time (float, epoch)

    def set(self, key, value, px=None, expires_at=None):
        """Store ``key``.

        ``px`` is a time-to-live in milliseconds (from SET ... PX).
        ``expires_at`` is an absolute epoch time, used when loading an RDB file.
        """
        self._data[key] = value
        if expires_at is not None:
            self._expires[key] = expires_at
        elif px is not None:
            self._expires[key] = time.time() + (px / 1000.0)
        else:
            self._expires.pop(key, None)

    def get(self, key):
        if self._is_expired(key):
            self._delete(key)
            return None
        return self._data.get(key)

    def keys(self):
        self._purge_expired()
        return list(self._data)

    def size(self):
        self._purge_expired()
        return len(self._data)

    def _is_expired(self, key):
        deadline = self._expires.get(key)
        return deadline is not None and deadline <= time.time()

    def _purge_expired(self):
        now = time.time()
        for key in list(self._expires):
            if self._expires[key] <= now:
                self._delete(key)

    def _delete(self, key):
        self._data.pop(key, None)
        self._expires.pop(key, None)
