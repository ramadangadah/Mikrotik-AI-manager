"""
Per-metric anomaly detection using scikit-learn's IsolationForest. Cheap
enough to run per-device per-metric on a schedule (not on every poll), and
catches things a fixed threshold can't: a device whose CPU normally sits at
5% suddenly pinning at 40% is anomalous even though 40% is nowhere near a
hardcoded "high CPU" threshold.

Falls back gracefully (returns not-anomalous) on too little data or any
sklearn error - this is a nice-to-have signal layered on top of the rule
engine, never a hard dependency for alerting to work.
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


def detect_anomaly(history: list[float], latest: float, contamination: float = 0.05) -> tuple[bool, float]:
    """
    Returns (is_anomalous, anomaly_score). Higher score = more anomalous.
    `history` should be prior values (not including `latest`), ideally 50+.
    """
    if len(history) < 20:
        return False, 0.0

    try:
        from sklearn.ensemble import IsolationForest
    except ImportError:
        return False, 0.0

    try:
        X = np.array(history, dtype=float).reshape(-1, 1)
        model = IsolationForest(contamination=contamination, random_state=42, n_estimators=100)
        model.fit(X)
        pred = model.predict(np.array([[latest]]))[0]
        score = -model.score_samples(np.array([[latest]]))[0]  # higher = more anomalous
        return bool(pred == -1), float(score)
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("anomaly detection failed: %s", e)
        return False, 0.0
