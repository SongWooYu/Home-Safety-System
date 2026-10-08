from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ShadowObservationLog:
    """Rate-limited, size-bounded JSONL diagnostics without image data."""

    def __init__(
        self,
        path: str | Path,
        interval_seconds: float = 1.0,
        max_bytes: int = 20 * 1024 * 1024,
    ):
        self.path = Path(path)
        self.interval_seconds = max(0.1, float(interval_seconds))
        self.max_bytes = max(1024, int(max_bytes))
        self.last_error: str | None = None
        self._next_write_at = 0.0
        self._lock = threading.Lock()

    def maybe_write(
        self,
        record: dict[str, Any],
        *,
        now: float | None = None,
        force: bool = False,
    ) -> bool:
        current = time.monotonic() if now is None else now
        with self._lock:
            if not force and current < self._next_write_at:
                return False
            self._next_write_at = current + self.interval_seconds
            payload = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **record,
            }
            encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._rotate_if_needed(len(encoded))
                with self.path.open("ab") as handle:
                    handle.write(encoded)
                self.last_error = None
                return True
            except OSError as exc:
                self.last_error = str(exc)
                return False

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        if not self.path.exists():
            return
        if self.path.stat().st_size + incoming_bytes <= self.max_bytes:
            return
        backup = self.path.with_name(self.path.name + ".1")
        backup.unlink(missing_ok=True)
        self.path.replace(backup)
