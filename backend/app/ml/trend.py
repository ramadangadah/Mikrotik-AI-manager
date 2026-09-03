"""
Lightweight trend analysis - no heavy ML needed for "is this metric getting
worse over time". A simple least-squares slope over a rolling window is
enough to say "signal has dropped 6 dBm over the last 12 hours" and project
forward to "will cross -80 dBm in about 2 days".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class TrendResult:
    slope_per_hour: float
    r_squared: float
    current_value: float
    n_points: int

    def hours_until(self, threshold: float) -> float | None:
        """Hours until the trend line crosses `threshold`, or None if it never will."""
        if self.slope_per_hour == 0:
            return None
        hours = (threshold - self.current_value) / self.slope_per_hour
        return hours if hours > 0 else None


def linear_trend(points: list[tuple[datetime, float]]) -> TrendResult | None:
    """points: list of (timestamp, value), any order, len >= 3."""
    if len(points) < 3:
        return None

    points = sorted(points, key=lambda p: p[0])
    t0 = points[0][0]
    xs = [(p[0] - t0).total_seconds() / 3600.0 for p in points]  # hours since first point
    ys = [p[1] for p in points]

    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    ss_xx = sum((x - mean_x) ** 2 for x in xs)
    ss_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    ss_yy = sum((y - mean_y) ** 2 for y in ys)

    if ss_xx == 0:
        return TrendResult(slope_per_hour=0.0, r_squared=0.0, current_value=ys[-1], n_points=n)

    slope = ss_xy / ss_xx
    r_squared = (ss_xy**2) / (ss_xx * ss_yy) if ss_yy > 0 else 0.0

    return TrendResult(slope_per_hour=slope, r_squared=r_squared, current_value=ys[-1], n_points=n)
