"""Annotated video export, adapted from sensors_fusion.ipynb (cell 15, section 10).

draw_yolo_boxes, draw_roi, draw_hud and draw_phase_label are the notebook's
OpenCV helpers. Differences: the colours are the app's source colours, the
HUD shows only the counts of the active mode, and the LiDAR bird's-eye view
is drawn with OpenCV (the notebook rendered it with matplotlib), so a whole
recording renders in seconds. Frames are piped into ffmpeg (H.264), so the
file plays in a browser (the notebook's mp4v does not).
"""
from __future__ import annotations

import subprocess
from typing import Any, Callable

import cv2
import numpy as np

FONT = cv2.FONT_HERSHEY_SIMPLEX


def hex_bgr(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b, g, r)


COLOR_LIDAR = hex_bgr("#0F9D8F")
COLOR_YOLO = hex_bgr("#16A34A")
COLOR_FUSED = hex_bgr("#4F46E5")
COLOR_NAVY = hex_bgr("#1B2A4A")
COLOR_GT = (255, 255, 255)          # notebook: white
COLOR_ROI = (0, 255, 255)           # notebook: yellow
COLOR_HUD_LIDAR = hex_bgr("#2DD4BF")  # lighter tints, readable on video with a black outline
COLOR_HUD_YOLO = hex_bgr("#4ADE80")
COLOR_HUD_FUSED = hex_bgr("#A5B4FC")
TURBO_LUT = cv2.applyColorMap(np.arange(256, dtype=np.uint8).reshape(-1, 1), cv2.COLORMAP_TURBO).reshape(256, 3)


# Source: sensors_fusion.ipynb, cell 15 (10.4) draw_yolo_boxes. The detections
# of the frame are passed in (already filtered by the confidence threshold).
def draw_yolo_boxes(canvas, dets, color=COLOR_YOLO):
    for d in dets:
        x1, y1, x2, y2 = (int(round(v)) for v in d["box"])
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
        cv2.putText(canvas, f"{d['conf']:.2f}", (x1, max(0, y1 - 6)),
                    FONT, 0.5, color, 1, cv2.LINE_AA)


# Source: sensors_fusion.ipynb, cell 15 (10.4) draw_roi, plus the "approximate calibration" label.
def draw_roi(canvas, roi_px, color=COLOR_ROI):
    cv2.polylines(canvas, [roi_px.astype(int)], True, color, 2)
    x, y = (int(v) for v in roi_px[np.argmin(roi_px[:, 1])])   # top-most corner
    cv2.putText(canvas, "ROI (approximate calibration)", (max(4, x), max(16, y - 8)),
                FONT, 0.45, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(canvas, "ROI (approximate calibration)", (max(4, x), max(16, y - 8)),
                FONT, 0.45, color, 1, cv2.LINE_AA)


# Source: sensors_fusion.ipynb, cell 15 (10.4) draw_hud. `lines` = [(text, colour)].
def draw_hud(canvas, lines):
    H = canvas.shape[0]
    y0 = H - 20 - 22 * (len(lines) - 1)
    for k, (txt, col) in enumerate(lines):
        cv2.putText(canvas, txt, (20, y0 + 22 * k),
                    FONT, 0.65, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(canvas, txt, (20, y0 + 22 * k),
                    FONT, 0.65, col, 1, cv2.LINE_AA)


# Source: sensors_fusion.ipynb, cell 15 (10.4) draw_phase_label. "-" instead of
# "–": OpenCV's Hershey fonts cannot draw the en dash.
def draw_phase_label(canvas, t_now, gt_segments):
    W = canvas.shape[1]
    for s, e, c in gt_segments:
        if s <= t_now < e:
            txt = f"GT phase: {c} people  ({s:.1f}-{e:.1f}s)"
            (tw, th), _ = cv2.getTextSize(txt, FONT, 0.6, 2)
            cv2.rectangle(canvas, (W//2 - tw//2 - 8, 20),
                          (W//2 + tw//2 + 8, 20 + th + 12), (0, 0, 0), -1)
            cv2.putText(canvas, txt, (W//2 - tw//2, 20 + th + 4),
                        FONT, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
            return


def hud_lines(mode: str, t: float, gt: float | None, lidar: float | None, yolo: int | None,
              fused: float | None) -> list[tuple[str, tuple[int, int, int]]]:
    """HUD text of the active mode only (format of the notebook's draw_hud)."""
    lines = [(f"t = {t:5.2f}s", (255, 255, 255))]
    if gt is not None:
        lines.append((f"GT          : {gt:.0f}", COLOR_GT))
    if mode in ("lidar", "fusion"):
        lines.append((f"LiDAR Qb2   : {'-' if lidar is None else f'{lidar:.0f}'}", COLOR_HUD_LIDAR))
    if mode in ("camera", "fusion"):
        lines.append((f"YOLO11m     : {'-' if yolo is None else yolo}", COLOR_HUD_YOLO))
    if mode == "fusion":
        lines.append((f"FUSED  ->   : {'-' if fused is None else f'{fused:.1f}'}", COLOR_HUD_FUSED))
    return lines


class BevRenderer:
    """Bird's-eye view of the LiDAR floor frame (u right, v up), drawn with OpenCV."""

    def __init__(self, background_cm: np.ndarray, zone_outline: np.ndarray, size: int = 576, margin: float = 0.4,
                 extra_outlines: list | None = None):
        self.size = size
        bg = background_cm[:, :2] / 100.0 if len(background_cm) else np.zeros((1, 2))
        if len(zone_outline):   # centre on the occupancy zone (people are counted there)
            zlo, zhi = np.min(zone_outline, 0), np.max(zone_outline, 0)
            pad = max(1.5, 0.5 * float(np.max(zhi - zlo)))
            lo, hi = zlo - pad, zhi + pad
        else:
            lo, hi = bg.min(0) - margin, bg.max(0) + margin
        span = max(hi[0] - lo[0], hi[1] - lo[1])
        self.scale = (size - 20) / span
        self.lo = lo
        self.off = np.array([(size - (hi[0] - lo[0]) * self.scale) / 2, (size - (hi[1] - lo[1]) * self.scale) / 2])
        self.hi_v = hi[1]

        base = np.full((size, size, 3), 255, np.uint8)
        for g in range(int(np.floor(lo[0])), int(np.ceil(hi[0])) + 1):          # 1 m grid
            x = int(self.px(np.array([[g, lo[1]]]))[0, 0])
            cv2.line(base, (x, 0), (x, size - 1), (238, 236, 233), 1)
        for g in range(int(np.floor(lo[1])), int(np.ceil(hi[1])) + 1):
            y = int(self.px(np.array([[lo[0], g]]))[0, 1])
            cv2.line(base, (0, y), (size - 1, y), (238, 236, 233), 1)
        bpx = self.px(bg).astype(int)
        ok = (bpx[:, 0] >= 0) & (bpx[:, 0] < size) & (bpx[:, 1] >= 0) & (bpx[:, 1] < size)
        base[bpx[ok, 1], bpx[ok, 0]] = (205, 205, 205)
        for extra in extra_outlines or []:      # zone footprints at other heights, faint
            z = self.px(np.asarray(extra, float))
            for i in range(len(z)):
                self._dashed(base, z[i], z[(i + 1) % len(z)], (215, 205, 195), dash=3, gap=5)
        if len(zone_outline):
            z = self.px(np.asarray(zone_outline, float))
            for i in range(len(z)):
                self._dashed(base, z[i], z[(i + 1) % len(z)], COLOR_NAVY)
        self.base = base

    def px(self, uv: np.ndarray) -> np.ndarray:
        x = self.off[0] + (uv[:, 0] - self.lo[0]) * self.scale
        y = self.off[1] + (self.hi_v - uv[:, 1]) * self.scale
        return np.column_stack([x, y])

    @staticmethod
    def _dashed(img, a, b, color, dash=8, gap=6):
        a, b = np.asarray(a, float), np.asarray(b, float)
        length = np.linalg.norm(b - a)
        if length == 0:
            return
        d = (b - a) / length
        pos = 0.0
        while pos < length:
            p0 = a + d * pos
            p1 = a + d * min(pos + dash, length)
            cv2.line(img, tuple(int(v) for v in p0), tuple(int(v) for v in p1), color, 1, cv2.LINE_AA)
            pos += dash + gap

    def frame(self, points_cm: np.ndarray | None, clusters: list[dict], trails: dict[int, list],
              hud: list | None, note: str | None = None) -> np.ndarray:
        img = self.base.copy()
        s = self.size
        if points_cm is not None and len(points_cm):
            p = self.px(points_cm[:, :2] / 100.0).astype(int)
            h = np.clip(points_cm[:, 2] / 100.0 / 2.2, 0, 1)
            col = TURBO_LUT[(h * 255).astype(int)]
            for dx in (0, 1):
                for dy in (0, 1):
                    x, y = p[:, 0] + dx, p[:, 1] + dy
                    ok = (x >= 0) & (x < s) & (y >= 0) & (y < s)
                    img[y[ok], x[ok]] = col[ok]
        for tid, pos in trails.items():       # fading trail: older = lighter
            if len(pos) < 2:
                continue
            pp = self.px(np.asarray(pos)).astype(int)
            for i in range(1, len(pp)):
                a = i / len(pp)
                c = tuple(int(255 - (255 - v) * a) for v in COLOR_LIDAR)
                cv2.line(img, tuple(pp[i - 1]), tuple(pp[i]), c, 2, cv2.LINE_AA)
        for c in clusters:
            u, v, w, d = c["u"], c["v"], c["w"], c["d"]
            p0 = self.px(np.array([[u - w / 2, v + d / 2]]))[0].astype(int)
            p1 = self.px(np.array([[u + w / 2, v - d / 2]]))[0].astype(int)
            cv2.rectangle(img, tuple(p0), tuple(p1), COLOR_LIDAR, 2 if c.get("confirmed") else 1)
            label = (f"#{c['track_id']} " if c.get("track_id") is not None else "") + f"{c['top']:.2f}m"
            cv2.putText(img, label, (int(p0[0]), max(12, int(p0[1]) - 5)), FONT, 0.42, COLOR_LIDAR, 1, cv2.LINE_AA)
        if note:
            (tw, _), _ = cv2.getTextSize(note, FONT, 0.5, 1)
            cv2.putText(img, note, (s // 2 - tw // 2, 30), FONT, 0.5, COLOR_NAVY, 1, cv2.LINE_AA)
        if hud:
            draw_hud(img, hud)
        return img


def open_ffmpeg(ffmpeg: str, out_path: str, width: int, height: int, fps: float) -> subprocess.Popen:
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}", "-r", f"{fps:.6f}", "-i", "-",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", out_path]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)


def lidar_frame_at(t_lidar_video: np.ndarray, t: float, period: float) -> int | None:
    """Index of the LiDAR frame shown at video time t (the latest one at or before t)."""
    j = int(np.searchsorted(t_lidar_video, t, side="right")) - 1
    if j < 0 or t > t_lidar_video[-1] + period:
        return None
    return j


def render_video(
    out_path: str,
    mode: str,
    *,
    ffmpeg: str,
    fps: float,
    n_frames: int,
    video_path: str | None,
    yolo_dets: list[list[dict]] | None,
    roi_px: np.ndarray | None,
    lidar: dict[str, Any] | None,
    gt_segments: list[tuple[float, float, int]] | None,
    gt_at: Callable[[float], float | None],
    fused_at: Callable[[float], float | None],
    on_progress: Callable[[int, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    """Render the view of `mode` over the video timeline (video fps) into an H.264 mp4.

    lidar: {"t_video": array, "smooth": list, "clusters": list per frame,
            "points": int16 array (cm), "offsets": array, "scene": {...}, "period": s}
    """
    cap = cv2.VideoCapture(video_path) if video_path and mode in ("camera", "fusion") else None
    bev = None
    if lidar is not None and mode in ("lidar", "fusion"):
        scene = lidar["scene"]
        outlines = scene["zone"].get("outlines") or {}
        bev = BevRenderer(np.asarray(scene["background"], dtype=float),
                          np.asarray(scene["zone"]["outline"], dtype=float),
                          size=576 if mode == "fusion" else 720,
                          extra_outlines=[v for k, v in outlines.items() if k != "1.0"])
    cam_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) if cap else 0
    cam_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) if cap else 0
    banner = 64 if mode == "fusion" else 0
    if mode == "camera":
        W, H = cam_w, cam_h
    elif mode == "lidar":
        W, H = bev.size, bev.size
    else:
        W, H = cam_w + bev.size, max(cam_h, bev.size) + banner
    W, H = W + W % 2, H + H % 2
    proc = open_ffmpeg(ffmpeg, out_path, W, H, fps)

    def lidar_state(t: float):
        if bev is None:
            return None, [], {}, None
        j = lidar_frame_at(lidar["t_video"], t, lidar["period"])
        if j is None:
            return None, [], {}, None
        pts = lidar["points"][lidar["offsets"][j]:lidar["offsets"][j + 1]]
        trails: dict[int, list] = {}
        k = j
        while k >= 0 and lidar["t_video"][j] - lidar["t_video"][k] <= 2.0:
            for c in lidar["clusters"][k]:
                if c.get("track_id") is not None:
                    trails.setdefault(c["track_id"], []).append((c["u"], c["v"]))
            k -= 1
        trails = {tid: p[::-1] for tid, p in trails.items()}
        return pts, lidar["clusters"][j], trails, lidar["smooth"][j]

    try:
        for i in range(n_frames):
            if should_stop is not None and should_stop():
                break
            t = i / fps
            gt = gt_at(t)
            pts, clusters, trails, lidar_count = lidar_state(t)
            yolo_n = len(yolo_dets[i]) if yolo_dets is not None and i < len(yolo_dets) else None
            hud = hud_lines(mode, t, gt, lidar_count, yolo_n, fused_at(t))
            if cap is not None:
                ok, frame = cap.read()
                if not ok:
                    frame = np.zeros((cam_h, cam_w, 3), np.uint8)
                if roi_px is not None:
                    draw_roi(frame, roi_px)
                if yolo_dets is not None and i < len(yolo_dets):
                    draw_yolo_boxes(frame, yolo_dets[i])
                if gt_segments:
                    draw_phase_label(frame, t, gt_segments)
                draw_hud(frame, hud)
            if mode == "camera":
                img = frame
            elif mode == "lidar":
                img = bev.frame(pts, clusters, trails, hud,
                                None if lidar_count is not None else "No LiDAR data at this time")
            else:
                side = bev.frame(pts, clusters, trails, None,
                                 None if lidar_count is not None else "No LiDAR data at this time")
                img = np.full((H, W, 3), 255, np.uint8)
                img[banner:banner + cam_h, :cam_w] = frame
                img[banner:banner + bev.size, cam_w:cam_w + bev.size] = side
                fused = fused_at(t)
                txt = f"FUSED (Stack-GBT): {'-' if fused is None else f'{fused:.2f}'} people"
                if gt is not None:
                    txt += f"   |   GT: {gt:.0f}"
                cv2.putText(img, txt, (20, 44), FONT, 1.0, COLOR_FUSED, 2, cv2.LINE_AA)
            if img.shape[0] != H or img.shape[1] != W:
                img = cv2.copyMakeBorder(img, 0, H - img.shape[0], 0, W - img.shape[1],
                                         cv2.BORDER_CONSTANT, value=(255, 255, 255))
            proc.stdin.write(np.ascontiguousarray(img).tobytes())
            if on_progress is not None and (i % 5 == 0 or i == n_frames - 1):
                on_progress(i + 1, n_frames)
    finally:
        if cap is not None:
            cap.release()
        try:
            proc.stdin.close()
        except OSError:
            pass
        err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
        code = proc.wait()
    if code != 0:
        raise RuntimeError(f"ffmpeg failed (exit {code}): {err[-300:]}")
