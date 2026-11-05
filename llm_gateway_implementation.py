"""
Agentic Universe - LLM Gateway Technical Assessment
Requirement: Python 3.10+, standard library only.
"""

import asyncio
import random
import time
from dataclasses import dataclass


# ---------- Provided: do not modify ----------

class TransientError(Exception):
    pass


class RateLimitError(TransientError):
    pass


class ProviderUnavailable(TransientError):
    pass


class InvalidRequestError(Exception):
    pass


class MockProvider:

    def __init__(self, name, fail_rate=0.3,
                 latency=(0.1, 1.5), max_concurrency=5):

        self.name = name
        self.fail_rate = fail_rate
        self.latency = latency
        self.max_concurrency = max_concurrency

        self._in_flight = 0
        self.peak_in_flight = 0

    async def generate(self, prompt: str) -> str:

        if not prompt.strip():
            raise InvalidRequestError("empty prompt")

        self._in_flight += 1
        self.peak_in_flight = max(
            self.peak_in_flight, self._in_flight
        )

        try:
            if self._in_flight > self.max_concurrency:
                raise RateLimitError(
                    f"{self.name}: concurrency exceeded"
                )

            await asyncio.sleep(
                random.uniform(*self.latency)
            )

            r = random.random()

            if r < self.fail_rate / 2:
                raise RateLimitError(f"{self.name}: 429")

            if r < self.fail_rate:
                raise ProviderUnavailable(
                    f"{self.name}: 503"
                )

            return f"[{self.name}] answer to: {prompt[:30]}"

        finally:
            self._in_flight -= 1


@dataclass
class Result:
    text: str
    provider: str
    attempts: int
    latency_ms: float


class AllProvidersFailed(Exception):

    def __init__(self, errors):
        super().__init__(f"all providers failed: {errors}")
        self.errors = errors


# ---------- Your code ----------

@dataclass
class _CircuitBreakerState:
    """Tracks sequential failures and cooling-off intervals per provider."""
    consecutive_failures: int = 0
    cooldown_until: float = 0.0

    def is_open(self, now: float) -> bool:
        return now < self.cooldown_until

    def record_success(self):
        self.consecutive_failures = 0
        self.cooldown_until = 0.0

    def record_failure(self, now: float, threshold: int = 5, recovery_timeout_s: float = 10.0):
        self.consecutive_failures += 1
        if self.consecutive_failures >= threshold:
            self.cooldown_until = now + recovery_timeout_s


class LLMGateway:

    def __init__(
        self,
        providers,
        timeout_s: float = 1.0,
        max_retries: int = 2,
        base_backoff_s: float = 0.1,
        cb_failure_threshold: int = 5,
        cb_recovery_timeout_s: float = 10.0
    ):
        if not providers:
            raise ValueError("At least one provider required")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if base_backoff_s < 0:
            raise ValueError("base_backoff_s cannot be negative")

        self.providers = list(providers)
        self.timeout_s = float(timeout_s)
        self.max_retries = int(max_retries)
        self.base_backoff_s = float(base_backoff_s)
        self.cb_failure_threshold = int(cb_failure_threshold)
        self.cb_recovery_timeout_s = float(cb_recovery_timeout_s)

        # Dedicated concurrency limits per provider instance
        self._semaphores = {
            id(p): asyncio.Semaphore(p.max_concurrency)
            for p in self.providers
        }

        # Bonus: Track state for consecutive failures and temporary tripping
        self._circuit_breakers = {
            id(p): _CircuitBreakerState()
            for p in self.providers
        }

    async def complete(self, prompt: str) -> Result:
        start_time = time.monotonic()
        total_attempts = 0
        errors = []

        # Iterate providers in strict priority order
        for provider in self.providers:
            provider_id = id(provider)
            cb = self._circuit_breakers[provider_id]
            sem = self._semaphores[provider_id]

            # Circuit breaker check: skip provider if temporarily tripped
            now = time.monotonic()
            if cb.is_open(now):
                errors.append(
                    (provider.name, ProviderUnavailable(f"{provider.name}: circuit breaker open"))
                )
                continue

            # Attempts allowed: 1 initial attempt + max_retries
            for retry in range(self.max_retries + 1):
                try:
                    # Enforce per-provider concurrency cap
                    async with sem:
                        total_attempts += 1
                        # Enforce timeout per individual attempt
                        response = await asyncio.wait_for(
                            provider.generate(prompt),
                            timeout=self.timeout_s
                        )

                    # Reset consecutive failure counter on success
                    cb.record_success()
                    latency_ms = (time.monotonic() - start_time) * 1000.0

                    return Result(
                        text=response,
                        provider=provider.name,
                        attempts=total_attempts,
                        latency_ms=latency_ms
                    )

                except InvalidRequestError:
                    # Fail fast: do not retry and do not fall back
                    raise

                except (TransientError, asyncio.TimeoutError) as exc:
                    cb.record_failure(
                        time.monotonic(),
                        threshold=self.cb_failure_threshold,
                        recovery_timeout_s=self.cb_recovery_timeout_s
                    )
                    errors.append((provider.name, exc))

                    if retry < self.max_retries:
                        # Full jitter exponential backoff: sleep in [0, base * 2^retry]
                        max_backoff = self.base_backoff_s * (2 ** retry)
                        sleep_duration = random.uniform(0.0, max_backoff)
                        await asyncio.sleep(sleep_duration)
                    else:
                        # Exhausted retries for this provider; fall back to next
                        break

        # If every provider fails across all attempts
        raise AllProvidersFailed(errors)


# ---------- Harness: do not modify ----------

async def main():

    primary = MockProvider(
        "primary",
        fail_rate=0.4,
        latency=(0.1, 1.5),
        max_concurrency=5
    )

    fallback = MockProvider(
        "fallback",
        fail_rate=0.1,
        latency=(0.2, 0.6),
        max_concurrency=10
    )

    gw = LLMGateway([primary, fallback])

    prompts = [
        f"question {i}" for i in range(50)
    ] + [""]

    results = await asyncio.gather(
        *(gw.complete(p) for p in prompts),
        return_exceptions=True
    )

    ok = [
        r for r in results
        if isinstance(r, Result)
    ]

    print(f"success: {len(ok)}/{len(prompts)}")

    print(
        "by provider:",
        {
            p: sum(r.provider == p for r in ok)
            for p in ("primary", "fallback")
        }
    )

    print(
        "errors:",
        [
            type(r).__name__
            for r in results
            if isinstance(r, Exception)
        ]
    )

    print(
        "peak in-flight:",
        primary.peak_in_flight,
        fallback.peak_in_flight
    )

    assert (
        primary.peak_in_flight <= 5
        and fallback.peak_in_flight <= 10
    ), "concurrency cap violated"


# Production improvements:
# 1. Distributed rate limiting & concurrency (e.g., Redis token bucket / sliding window) across multiple scaled gateway pods.
# 2. Structured telemetry/logging with OpenTelemetry metrics for TTFT (time-to-first-token), request latency histograms, and per-provider SLA monitoring.
# 3. Request hedging/speculative retries for long-tail voice latency and streaming token cancellation via asyncio.Event/Task primitives.


if __name__ == "__main__":
    asyncio.run(main())