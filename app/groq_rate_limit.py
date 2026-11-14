"""Bound concurrent Groq calls and retain rolling usage budgets across restarts."""

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
        state_path, *, max_concurrency=1, clock=time.time, sleep=time.sleep,
    ):
        if min(requests_per_minute, tokens_per_minute, tokens_per_day) < 1:
            raise ValueError("Groq rate limits must be positive.")
        if max_concurrency < 1:
            raise ValueError("Groq max_concurrency must be positive.")
        self.requests_per_minute = requests_per_minute
        self.tokens_per_minute = tokens_per_minute
        self.tokens_per_day = tokens_per_day
        self.state_path = Path(state_path)
        self.clock = clock
        self.sleep = sleep
        self.lock = threading.Lock()
        self.changed = threading.Condition(self.lock)
        self.slots = threading.BoundedSemaphore(max_concurrency)
        self.in_flight = set()
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
            "entries": self._usage_entries(self.clock()),
            "blocked_until": self.blocked_until,
        }), encoding="utf-8")
        temporary.replace(self.state_path)

    def _usage_entries(self, now):
        # Pending calls retain their full reservation even when they run longer
        # than a budget window. Persist them conservatively on every save too.
        return sorted(
            [now if id(entry) in self.in_flight else entry[0], entry[1]]
            for entry in self.entries
        )

    def _token_delay(self, entries, now, window, limit, reservation):
        entries = [entry for entry in entries if entry[0] + window > now]
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
            with self.changed:
                now = self.clock()
                self.entries = [
                    entry for entry in self.entries
                    if id(entry) in self.in_flight or entry[0] + DAY > now
                ]
                entries = self._usage_entries(now)
                minute_entries = [entry for entry in entries if entry[0] + MINUTE > now]
                request_delay = 0.0
                if len(minute_entries) >= self.requests_per_minute:
                    request_delay = minute_entries[-self.requests_per_minute][0] + MINUTE - now
                delay = max(
                    self.blocked_until - now,
                    request_delay,
                    self._token_delay(entries, now, MINUTE, self.tokens_per_minute, tokens),
                    self._token_delay(entries, now, DAY, self.tokens_per_day, tokens),
                )
                if delay <= 0:
                    entry = [now, tokens]
                    self.entries.append(entry)
                    self.in_flight.add(id(entry))
                    # Save before sending so a crash cannot erase a charged call.
                    try:
                        self._save()
                    except OSError:
                        self.in_flight.remove(id(entry))
                        self.entries = [item for item in self.entries if item is not entry]
                        self.changed.notify_all()
                        raise
                    return entry
                LOGS.info("Waiting %.1f seconds for the Groq rate budget", delay)
                if self.in_flight:
                    # Release the state lock while waiting, and wake promptly
                    # when a completion releases unused reserved tokens.
                    self.changed.wait(timeout=delay)
                    continue
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
        """Run within the concurrency cap; retries share all usage budgets."""
        if reserved_tokens < 1 or reserved_tokens > min(self.tokens_per_minute, self.tokens_per_day):
            raise ValueError("This message exceeds the configured Groq token budget for one request.")
        with self.slots:
            for attempt in range(3):
                entry = self._reserve(reserved_tokens)
                actual_tokens = None
                try:
                    completion = request()
                    actual_tokens = getattr(getattr(completion, "usage", None), "total_tokens", None)
                    return completion
                except RateLimitError as error:
                    delay = self._retry_delay(error, attempt)
                    with self.changed:
                        self.blocked_until = max(self.blocked_until, self.clock() + delay)
                    LOGS.warning("Groq rate limited the request; delaying the queue by %.1f seconds", delay)
                    if attempt == 2:
                        raise
                finally:
                    # Charge unsuccessful/ambiguous calls their full reservation.
                    # Use completion time to avoid expiring a long request early.
                    with self.changed:
                        if isinstance(actual_tokens, int) and actual_tokens > 0:
                            entry[1] = actual_tokens
                        entry[0] = self.clock()
                        self.in_flight.remove(id(entry))
                        self.entries.sort(key=lambda item: item[0])
                        try:
                            self._save()
                        finally:
                            self.changed.notify_all()
