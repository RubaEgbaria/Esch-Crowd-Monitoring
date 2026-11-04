"""Ground-truth segments: parsing, normalisation and checks.

A segment is ``{"start", "end", "people"}`` where start/end are seconds of
video time, ``"T"`` (video duration) or ``"T-x"`` (x seconds before the end),
exactly as in the notebooks. Tokens are normalised to the canonical forms the
notebook's ``resolve_segments`` expects (a float, ``"T"`` or ``"T-<x>"``).

Sampling follows ``sample_gt`` in sensors_fusion.ipynb (cell 5): a segment
covers ``[start, end)``, later segments overwrite earlier ones, and times not
covered by any segment count as 0 people.
"""
from __future__ import annotations

import math
import re
from typing import Any

from pipeline.config import GT_PRESETS
from pipeline.sync import resolve_segments

from .errors import AppError

_T_RE = re.compile(r"^T(?:-(\d+(?:\.\d*)?|\.\d+))?$")
MAX_SEGMENTS = 100


def _fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else repr(float(x))


def normalize_token(value: Any) -> float | str:
    """Return a float (seconds), "T" or "T-<x>"; raise ValueError otherwise."""
    if isinstance(value, bool):
        raise ValueError(f"'{value}' is not a valid time")
    if isinstance(value, (int, float)):
        v = float(value)
        if not math.isfinite(v) or v < 0:
            raise ValueError(f"'{value}' is not a valid time (must be ≥ 0)")
        return v
    if isinstance(value, str):
        s = value.strip().replace(" ", "").upper()
        if not s:
            raise ValueError("A time is empty")
        try:
            v = float(s)
        except ValueError:
            pass
        else:
            if not math.isfinite(v) or v < 0:
                raise ValueError(f"'{value}' is not a valid time (must be ≥ 0)")
            return v
        m = _T_RE.match(s)
        if m:
            return "T" if m.group(1) is None else f"T-{_fmt(float(m.group(1)))}"
    raise ValueError(
        f"'{value}' is not a valid time. Use seconds (e.g. 4.5), "
        "'T' (end of the video) or 'T-x' (x seconds before the end)."
    )


def normalize_segments(raw: list[Any]) -> list[dict[str, Any]]:
    """Validate the shape of user-entered segments (no video duration needed)."""
    if not raw:
        raise AppError("Add at least one ground-truth segment, or turn ground truth off.",
                       code="gt_invalid", status=422)
    if len(raw) > MAX_SEGMENTS:
        raise AppError(f"Too many ground-truth segments (max {MAX_SEGMENTS}).",
                       code="gt_invalid", status=422)
    out = []
    for i, seg in enumerate(raw, 1):
        if isinstance(seg, dict):
            start, end, people = seg.get("start"), seg.get("end"), seg.get("people")
        elif isinstance(seg, (list, tuple)) and len(seg) == 3:
            start, end, people = seg
        else:
            raise AppError(f"Segment {i}: expected start, end and people.", code="gt_invalid", status=422)
        try:
            start_n = normalize_token(start)
            end_n = normalize_token(end)
        except ValueError as e:
            raise AppError(f"Segment {i}: {e}", code="gt_invalid", status=422) from None
        if isinstance(people, bool) or not isinstance(people, (int, float)) or \
                float(people) != int(people) or people < 0:
            raise AppError(f"Segment {i}: people must be a whole number ≥ 0.",
                           code="gt_invalid", status=422)
        out.append({"start": start_n, "end": end_n, "people": int(people)})
    return out


def normalize_ground_truth(gt: dict[str, Any] | None) -> dict[str, Any] | None:
    if not gt:
        return None
    preset = gt.get("preset")
    if preset is not None and preset not in GT_PRESETS:
        preset = None  # "custom" or unknown: keep the segments, drop the label
    return {"preset": preset, "segments": normalize_segments(gt.get("segments") or [])}


def check_segments(segments: list[dict[str, Any]], T: float) -> dict[str, Any]:
    """Resolve "T"/"T-x" against the video duration and report problems."""
    resolved = resolve_segments([(s["start"], s["end"], s["people"]) for s in segments], T)
    errors: list[str] = []
    warnings: list[str] = []
    for i, (s, e, _c) in enumerate(resolved, 1):
        if s < 0 or e < 0:
            errors.append(f"Segment {i} starts before 0 s (the video is {T:.2f} s long).")
        if e <= s:
            errors.append(f"Segment {i}: the end ({e:.2f} s) must be after the start ({s:.2f} s).")
        elif s >= T:
            warnings.append(f"Segment {i} starts after the end of the video ({s:.2f} s ≥ {T:.2f} s).")
        elif e > T + 1e-6:
            warnings.append(f"Segment {i} ends after the video ({e:.2f} s > {T:.2f} s); the extra part is ignored.")

    if not errors:
        # Overlaps: the later segment wins (same as the notebook's sample_gt).
        for i in range(len(resolved)):
            for j in range(i + 1, len(resolved)):
                a0, a1, _ = resolved[i]
                b0, b1, _ = resolved[j]
                lo, hi = max(a0, b0), min(a1, b1)
                if hi - lo > 1e-6:
                    warnings.append(
                        f"Segments {i + 1} and {j + 1} overlap ({lo:.2f}–{hi:.2f} s); "
                        f"segment {j + 1} wins there, as in the notebook."
                    )
        # Gaps inside [0, T): counted as 0 people by sample_gt.
        cursor = 0.0
        for s, e, _ in sorted(resolved):
            if s - cursor > 1e-6 and cursor < T:
                warnings.append(
                    f"No segment covers {cursor:.2f}–{min(s, T):.2f} s; the notebook counts 0 people there."
                )
            cursor = max(cursor, e)
        if T - cursor > 1e-6:
            warnings.append(
                f"No segment covers {cursor:.2f}–{T:.2f} s; the notebook counts 0 people there."
            )

    people = {c for _, _, c in resolved}
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "T": T,
        "resolved": [{"start": s, "end": e, "people": c} for s, e, c in resolved],
        "constant": len(people) == 1,
    }


def presets_payload() -> list[dict[str, Any]]:
    out = []
    for key, p in GT_PRESETS.items():
        out.append({
            "key": key,
            "label": p["label"],
            "description": p["description"],
            "source": p["source"],
            "segments": [{"start": s, "end": e, "people": c} for s, e, c in p["segments"]],
        })
    return out
