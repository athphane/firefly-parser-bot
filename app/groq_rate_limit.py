"""Serialize Groq calls and retain rolling usage budgets across restarts."""

import json
import logging
import math
import threading
import time
from email.utils import parsedate_to_datetime
from pathlib import Path

from groq import RateLimitError

LOGS = logging.getLogger(__name__)
MINUTE = 61.0  # One second of margin at window boundaries.
DAY = 86401.0


class GroqRateLimiter:
    def __init__(
        self, requests_per_minute, tokens_per_minute, tokens_per_day,
        state_path, *, clock=time.time, sleep=time.sleep,
    ):
        if min(requests_per_minute, tokens_per_minute, tokens_per_day) < 1:
            raise ValueError("Groq rate limits must be positive.")
        self.requests_per_minute = requests_per_minute
        self.tokens_per_minute = tokens_per_minute
        self.tokens_per_day = tokens_per_day
        self.state_path = Path(state_path)
        self.clock = clock
        self.sleep = sleep
        self.lock = threading.Lock()
        self.entries = []
        self.blocked_until = 0.0
        if self.state_path.exists():
            try:
                state = json.loads(self.state_path.read_text(encoding="utf-8"))
                self.entries = state["entries"]
                self.blocked_until = state["blocked_until"]
                if not isinstance(self.entries, list) or not all(
                    isinstance(entry, list) and len(entry) == 2
                    and isinstance(entry[0], (int, float)) and math.isfinite(entry[0])
                    and isinstance(entry[1], int) and entry[1] >= 0
                    for entry in self.entries
                ):
                    raise ValueError("Invalid usage entries")
                if not isinstance(self.blocked_until, (int, float)) or not math.isfinite(self.blocked_until):
                    raise ValueError("Invalid cooldown")
                self.entries.sort(key=lambda entry: entry[0])
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise RuntimeError(f"Could not load Groq usage from {self.state_path}: {error}") from error

    def _save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({
            "entries": self.entries,
            "blocked_until": self.blocked_until,
        }), encoding="utf-8")
        temporary.replace(self.state_path)

    def _token_delay(self, now, window, limit, reservation):
        entries = [entry for entry in self.entries if entry[0] + window > now]
        total = sum(entry[1] for entry in entries) + reservation
        if total <= limit:
            return 0.0
        for timestamp, tokens in entries:
            total -= tokens
            if total <= limit:
                return timestamp + window - now
        return 0.0

    def _reserve(self, tokens):
        while True:
            now = self.clock()
            self.entries = [entry for entry in self.entries if entry[0] + DAY > now]
            minute_entries = [entry for entry in self.entries if entry[0] + MINUTE > now]
            request_delay = 0.0
            if len(minute_entries) >= self.requests_per_minute:
                request_delay = minute_entries[-self.requests_per_minute][0] + MINUTE - now
            delay = max(
                self.blocked_until - now,
                request_delay,
                self._token_delay(now, MINUTE, self.tokens_per_minute, tokens),
                self._token_delay(now, DAY, self.tokens_per_day, tokens),
            )
            if delay <= 0:
                entry = [now, tokens]
                self.entries.append(entry)
                # Save before sending so a crash cannot erase a charged call.
                self._save()
                return entry
            LOGS.info("Waiting %.1f seconds for the Groq rate budget", delay)
            self.sleep(delay)

    def _retry_delay(self, error, attempt):
        value = error.response.headers.get("retry-after")
        try:
            delay = float(value)
        except (TypeError, ValueError):
            try:
                delay = parsedate_to_datetime(value).timestamp() - self.clock()
            except (TypeError, ValueError, OverflowError):
                delay = 60.0 * (2 ** attempt)
        if not math.isfinite(delay) or delay < 0:
            delay = 60.0 * (2 ** attempt)
        return max(delay, 1.0) + 1.0

    def run(self, request, reserved_tokens):
        """Run one request at a time; retries also consume the shared budget."""
        if reserved_tokens < 1 or reserved_tokens > min(self.tokens_per_minute, self.tokens_per_day):
            raise ValueError("This message exceeds the configured Groq token budget for one request.")
        with self.lock:
            for attempt in range(3):
                entry = self._reserve(reserved_tokens)
                try:
                    completion = request()
                    actual_tokens = getattr(getattr(completion, "usage", None), "total_tokens", None)
                    if isinstance(actual_tokens, int) and actual_tokens > 0:
                        entry[1] = actual_tokens
                    return completion
                except RateLimitError as error:
                    delay = self._retry_delay(error, attempt)
                    self.blocked_until = max(self.blocked_until, self.clock() + delay)
                    LOGS.warning("Groq rate limited the request; delaying the queue by %.1f seconds", delay)
                    if attempt == 2:
                        raise
                finally:
                    # Charge unsuccessful/ambiguous calls their full reservation.
                    # Use completion time to avoid expiring a long request early.
                    entry[0] = self.clock()
                    self._save()
