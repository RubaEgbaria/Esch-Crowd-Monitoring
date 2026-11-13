"""Counting metrics, ported from sensors_fusion.ipynb (cell 16)."""
from __future__ import annotations

import numpy as np


# Source: sensors_fusion.ipynb, cell 16 ("Extra counting metrics: MAE, RMSE, Bias, Exact-match")
def counting_metrics(pred, gt):
    pred = np.asarray(pred, dtype=float)
    gt   = np.asarray(gt,   dtype=float)
    err  = pred - gt

    tp = np.minimum(pred, gt).sum()
    fp = np.maximum(pred - gt, 0).sum()
    fn = np.maximum(gt - pred, 0).sum()
    P  = tp / (tp + fp) if tp + fp else 0
    R  = tp / (tp + fn) if tp + fn else 0
    F  = 2 * P * R / (P + R) if P + R else 0

    return {
        "Precision":   100 * P,
        "Recall":      100 * R,
        "F1 Score":    100 * F,
        "MAE":         np.abs(err).mean(),
        "RMSE":        np.sqrt((err ** 2).mean()),
        "Bias":        err.mean(),          # + over-count, - under-count
        "Exact %":     100 * np.mean(err == 0),
        "Within ±1 %": 100 * np.mean(np.abs(err) <= 1),
    }
