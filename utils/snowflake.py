import threading
import time

# Custom epoch: 2024-01-01 00:00:00 UTC (milliseconds)
_EPOCH = 1704067200000

_TIMESTAMP_BITS = 41
_MACHINE_BITS = 10
_SEQUENCE_BITS = 12

_MAX_SEQUENCE = (1 << _SEQUENCE_BITS) - 1  # 4095


class SnowflakeGenerator:
    """Thread-safe snowflake ID generator (single machine)."""

    def __init__(self, machine_id: int = 0):
        if not 0 <= machine_id < (1 << _MACHINE_BITS):
            raise ValueError(f"machine_id must be 0~{(1 << _MACHINE_BITS) - 1}")
        self._machine_id = machine_id
        self._sequence = 0
        self._last_timestamp = -1
        self._lock = threading.Lock()

    def _current_ms(self) -> int:
        return int(time.time() * 1000)

    def generate(self) -> int:
        with self._lock:
            ts = self._current_ms()

            # Clock went backward — wait until it catches up
            if ts < self._last_timestamp:
                ts = self._last_timestamp

            if ts == self._last_timestamp:
                self._sequence = (self._sequence + 1) & _MAX_SEQUENCE
                if self._sequence == 0:
                    # Sequence exhausted in this millisecond, wait for next ms
                    while ts <= self._last_timestamp:
                        ts = self._current_ms()
            else:
                self._sequence = 0

            self._last_timestamp = ts

            return (
                ((ts - _EPOCH) << (_MACHINE_BITS + _SEQUENCE_BITS))
                | (self._machine_id << _SEQUENCE_BITS)
                | self._sequence
            )


_generator = SnowflakeGenerator()


def generate_id() -> int:
    """Generate a unique snowflake ID."""
    return _generator.generate()
