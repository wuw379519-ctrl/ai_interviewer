from __future__ import annotations

import json
import threading

from .contracts import Object
from .database import iso, now


class Operations:
    def __init__(self, logging: bool) -> None:
        self.started = iso(now())
        self.items: dict[str, Object] = {}
        self.lock = threading.RLock()
        self.logging = logging

    def record(self, operation: str, status: int, elapsed: int, request_id: str) -> None:
        if operation not in {"candidate_write", "turn", "state", "score", "transcribe", "plan"}:
            return
        with self.lock:
            row = self.items.setdefault(operation, {"operation": operation, "requests": 0, "failures": 0,
                       "clientErrors": 0, "totalMs": 0, "maxMs": 0,
                       "buckets": [{"leMs": bound, "count": 0} for bound in [100, 500, 1000, 5000, 20000, None]]})
            for key, delta in [("requests", 1), ("failures", int(status >= 500)), ("clientErrors", int(400 <= status < 500)), ("totalMs", elapsed)]:
                row[key] = int(str(row[key])) + delta
            row["maxMs"] = max(int(str(row["maxMs"])), elapsed)
            from .service import objects
            buckets = objects(row["buckets"])
            for bucket in buckets:
                if bucket["leMs"] is None or elapsed <= int(str(bucket["leMs"])):
                    bucket["count"] = int(str(bucket["count"])) + 1
            row["buckets"] = buckets
        if self.logging:
            print(json.dumps({"event": "http.operation", "requestId": request_id, "operation": operation, "status": status, "elapsedMs": elapsed}), flush=True)

    def snapshot(self) -> Object:
        with self.lock:
            return {"startedAt": self.started, "sampledAt": iso(now()), "scope": "single-process", "items": list(self.items.values())}
