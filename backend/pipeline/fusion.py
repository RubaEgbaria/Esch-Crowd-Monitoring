"""LiDAR + YOLO count fusion, adapted from sensors_fusion.ipynb (cell 12, section 7).

The notebook fused three sources (camera app, LiDAR, YOLO). Here there are
two: the LiDAR smoothed count and the YOLO count, plus the mean YOLO box
confidence per frame. Median, Trimmed mean and Majority vote are dropped
(meaningless with two sources).

Honest predictions only: the learned methods are evaluated with the
notebook's blocked k-fold CV, and the fused value at time t is the
out-of-fold prediction of the fold model that did not train on t's block.
"""
from __future__ import annotations

from typing import Any, Callable

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error


# Source: sensors_fusion.ipynb, cell 12 (7.2 "Blocked cross-validation")
def blocked_cv_indices(N, k):
    """Return list of (train_idx, test_idx) with contiguous test blocks."""
    bounds = np.linspace(0, N, k + 1).astype(int)
    folds = []
    for i in range(k):
        test = np.arange(bounds[i], bounds[i + 1])
        train = np.setdiff1d(np.arange(N), test)
        folds.append((train, test))
    return folds


# Source: sensors_fusion.ipynb, cell 12 (7.3). The notebook hard-codes the 3
# columns (camera, LiDAR, YOLO); here it takes every column (LiDAR, YOLO).
def fit_weights_wavg(Xtr, ytr):
    """Least-squares non-negative weights (clipped)."""
    from scipy.optimize import nnls
    A = np.column_stack([Xtr[:, i] for i in range(Xtr.shape[1])])
    w, _ = nnls(A, ytr)
    if w.sum() == 0:
        w = np.ones(Xtr.shape[1])
    return w / w.sum()


# Source: sensors_fusion.ipynb, cell 12 (7.3)
def stack_with_conf(Xtr, ytr, Xte):
    # Xte here is [lidar, yolo, conf_yolo]  (the notebook also had the camera app)
    return GradientBoostingRegressor(
        max_depth=3, n_estimators=200, random_state=0
    ).fit(Xtr, ytr).predict(Xte)


# Source: sensors_fusion.ipynb, cell 12 (7.3 ENSEMBLES), two-source subset.
ENSEMBLES: dict[str, Callable] = {
    "Mean":           lambda Xtr, ytr, Xte: Xte.mean(axis=1),
    "WAvg (learned)": lambda Xtr, ytr, Xte: Xte @ fit_weights_wavg(Xtr, ytr),
    "Stack-LinReg":   lambda Xtr, ytr, Xte: LinearRegression().fit(Xtr, ytr).predict(Xte),
    "Stack-GBT":      lambda Xtr, ytr, Xte: GradientBoostingRegressor(
                          max_depth=2, n_estimators=200, random_state=0
                      ).fit(Xtr, ytr).predict(Xte),
}
CONF_METHOD = "Conf-aware GBT"
FUSION_METHODS = [*ENSEMBLES, CONF_METHOD]
LEARNED_METHODS = ["WAvg (learned)", "Stack-LinReg", "Stack-GBT", CONF_METHOD]
BASELINES = ["LiDAR only", "YOLO only"]


def evaluate(
    lidar: np.ndarray,
    yolo: np.ndarray,
    conf: np.ndarray,
    y: np.ndarray,
    k: int,
) -> dict[str, Any]:
    """Blocked-CV evaluation (sensors_fusion.ipynb cell 12, 7.4 + 7.5) with out-of-fold predictions.

    All arrays are on the evaluation window (grid points where both sensors
    and the ground truth exist). Returns the results table (MAE = mean of the
    fold MAEs, its std, RMSE = mean of the fold RMSEs, sorted by MAE), the
    out-of-fold predictions per method and the Auto choice.
    """
    X_lid, X_yolo = lidar.astype(float), yolo.astype(float)
    conf_yolo_grid = conf.astype(float)
    N = len(y)
    folds = blocked_cv_indices(N, k)

    results = {name: {"mae": [], "rmse": []} for name in ENSEMBLES}
    results[CONF_METHOD] = {"mae": [], "rmse": []}
    results["LiDAR only"] = {"mae": [], "rmse": []}
    results["YOLO only"] = {"mae": [], "rmse": []}
    oof = {name: np.full(N, np.nan) for name in FUSION_METHODS}

    for tr, te in folds:
        X2_tr = np.column_stack([X_lid[tr], X_yolo[tr]])
        X2_te = np.column_stack([X_lid[te], X_yolo[te]])
        y_tr, y_te = y[tr], y[te]

        for name, fn in ENSEMBLES.items():
            yhat = fn(X2_tr, y_tr, X2_te)
            oof[name][te] = yhat
            results[name]["mae"].append(mean_absolute_error(y_te, yhat))
            results[name]["rmse"].append(np.sqrt(mean_squared_error(y_te, yhat)))

        # confidence-aware (needs the conf column)
        X3_tr = np.column_stack([X_lid[tr], X_yolo[tr], conf_yolo_grid[tr]])
        X3_te = np.column_stack([X_lid[te], X_yolo[te], conf_yolo_grid[te]])
        yhat = stack_with_conf(X3_tr, y_tr, X3_te)
        oof[CONF_METHOD][te] = yhat
        results[CONF_METHOD]["mae"].append(mean_absolute_error(y_te, yhat))
        results[CONF_METHOD]["rmse"].append(np.sqrt(mean_squared_error(y_te, yhat)))

        # single-source baselines
        for label, arr in [("LiDAR only", X_lid), ("YOLO only", X_yolo)]:
            yhat = arr[te]
            results[label]["mae"].append(mean_absolute_error(y_te, yhat))
            results[label]["rmse"].append(np.sqrt(mean_squared_error(y_te, yhat)))

    rows = [{"method": name, "mae": float(np.mean(d["mae"])), "mae_std": float(np.std(d["mae"])),
             "rmse": float(np.mean(d["rmse"])), "kind": "baseline" if name in BASELINES else "fusion"}
            for name, d in results.items()]
    rows.sort(key=lambda r: r["mae"])
    auto = min((r for r in rows if r["kind"] == "fusion"), key=lambda r: r["mae"])["method"]
    return {"table": rows, "oof": oof, "auto": auto, "n": N, "folds": k}
