"""Compare what was written with what was received.

Everything in this module is pure: no database, no clock, no threads.
That keeps the part that decides "was anything lost?" easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Window:
    """A period when the listener was disconnected, in seconds since the run started."""

    start: float
    end: float

    def contains(self, t: float) -> bool:
        return self.start <= t <= self.end


@dataclass
class Report:
    sent: int
    received: int
    missing: list[int]
    duplicates: dict[int, int]
    out_of_order: int
    missing_ranges: list[tuple[int, int]]
    missing_by_window: list[int] = field(default_factory=list)
    missing_outside_windows: int = 0

    @property
    def delivered(self) -> int:
        return self.sent - len(self.missing)

    @property
    def delivery_rate(self) -> float:
        return 1.0 if self.sent == 0 else self.delivered / self.sent

    @property
    def ok(self) -> bool:
        return not self.missing and not self.duplicates and self.out_of_order == 0

    def to_dict(self) -> dict:
        return {
            "sent": self.sent,
            "received": self.received,
            "delivered": self.delivered,
            "delivery_rate": round(self.delivery_rate, 6),
            "missing": len(self.missing),
            "missing_ranges": [list(r) for r in self.missing_ranges],
            "duplicates": sum(c - 1 for c in self.duplicates.values()),
            "out_of_order": self.out_of_order,
            "missing_by_window": self.missing_by_window,
            "missing_outside_windows": self.missing_outside_windows,
            "ok": self.ok,
        }


def _ranges(sorted_values: list[int]) -> list[tuple[int, int]]:
    """Collapse sorted integers into inclusive (first, last) runs."""
    ranges: list[tuple[int, int]] = []
    for value in sorted_values:
        if ranges and value == ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], value)
        else:
            ranges.append((value, value))
    return ranges


def check(
    sent: list[int],
    received: list[int],
    sent_at: dict[int, float] | None = None,
    windows: list[Window] | None = None,
) -> Report:
    """Compare sent sequence numbers with the order they were received in.

    - missing: sent but never received
    - duplicates: received more than once (value -> times received)
    - out_of_order: first deliveries that arrived after a higher number had
      already been seen
    - missing_by_window: if send times and disconnect windows are given, how
      many missing changes were sent during each window
    """
    sent_set = set(sent)
    counts: dict[int, int] = {}
    out_of_order = 0
    highest = None

    for seq in received:
        if seq not in sent_set:
            # Not ours (or from an older run); ignore rather than miscount.
            continue
        counts[seq] = counts.get(seq, 0) + 1
        if counts[seq] > 1:
            continue
        if highest is not None and seq < highest:
            out_of_order += 1
        highest = seq if highest is None else max(highest, seq)

    missing = sorted(sent_set - counts.keys())
    duplicates = {seq: n for seq, n in counts.items() if n > 1}

    report = Report(
        sent=len(sent_set),
        received=len(received),
        missing=missing,
        duplicates=duplicates,
        out_of_order=out_of_order,
        missing_ranges=_ranges(missing),
    )

    if windows:
        by_window = [0] * len(windows)
        outside = 0
        for seq in missing:
            t = (sent_at or {}).get(seq)
            hit = (
                None
                if t is None
                else next((i for i, w in enumerate(windows) if w.contains(t)), None)
            )
            if hit is None:
                outside += 1
            else:
                by_window[hit] += 1
        report.missing_by_window = by_window
        report.missing_outside_windows = outside

    return report
