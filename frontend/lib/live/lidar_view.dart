import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/gestures.dart';
import 'package:flutter/foundation.dart';
import 'package:material_ui/material_ui.dart';

import '../theme.dart';
import 'live_models.dart';
import 'playback.dart';

/// Turbo colormap (polynomial approximation), x in [0, 1].
Color turbo(double x) {
  x = x.clamp(0.0, 1.0);
  final r = 0.13572138 + x * (4.61539260 + x * (-42.66032258 + x * (132.13108234 + x * (-152.94239396 + x * 59.28637943))));
  final g = 0.09140261 + x * (2.19418839 + x * (4.84296658 + x * (-14.18503333 + x * (4.27729857 + x * 2.82956604))));
  final b = 0.10667330 + x * (12.64194608 + x * (-60.58204836 + x * (110.36276771 + x * (-89.90310912 + x * 27.34824973))));
  int c(double v) => (v.clamp(0.0, 1.0) * 255).round();
  return Color.fromARGB(255, c(r), c(g), c(b));
}

const double kMaxHeight = 2.2; // colour scale of the foreground points (m)
const int _bins = 24;

/// Bird's-eye view of the LiDAR on a white canvas, synced to the video time with lag_s.
/// Pan with the mouse, zoom with the wheel, double-click to reset.
class LidarView extends StatefulWidget {
  const LidarView({
    super.key,
    required this.data,
    required this.lagS,
    required this.playback,
    required this.showBoxes,
    this.hud,
    this.aspectRatio = 16 / 9,
  });

  final LidarData data;
  final double lagS;
  final PlaybackController playback;
  final bool showBoxes;
  final Widget? hud;
  final double aspectRatio;

  @override
  State<LidarView> createState() => _LidarViewState();
}

class _LidarViewState extends State<LidarView> {
  double? _scale; // px per metre
  Offset _center = Offset.zero; // (u, v) at the centre of the view
  Size _size = Size.zero;
  double _startScale = 1;
  Offset _startCenter = Offset.zero;
  Offset _startFocal = Offset.zero;

  void _fit(Size size) {
    final pts = [...widget.data.zone, for (final o in widget.data.zoneOthers) ...o];
    double minU = 1e9, maxU = -1e9, minV = 1e9, maxV = -1e9;
    if (pts.isEmpty) {
      final bg = widget.data.background;
      for (var i = 0; i < bg.length; i += 2) {
        minU = math.min(minU, bg[i]);
        maxU = math.max(maxU, bg[i]);
        minV = math.min(minV, bg[i + 1]);
        maxV = math.max(maxV, bg[i + 1]);
      }
    } else {
      for (final p in pts) {
        minU = math.min(minU, p[0]);
        maxU = math.max(maxU, p[0]);
        minV = math.min(minV, p[1]);
        maxV = math.max(maxV, p[1]);
      }
      const pad = 1.0;
      minU -= pad;
      maxU += pad;
      minV -= pad;
      maxV += pad;
    }
    _center = Offset((minU + maxU) / 2, (minV + maxV) / 2);
    _scale = math.min(size.width / (maxU - minU), size.height / (maxV - minV)) * 0.95;
  }

  @override
  void didUpdateWidget(LidarView old) {
    super.didUpdateWidget(old);
    if (old.data.key != widget.data.key && old.data.zone.isEmpty != widget.data.zone.isEmpty) _scale = null;
  }

  void _zoom(double factor, Offset focal) {
    final s = _scale ?? 1;
    final before = _toWorld(focal, s, _center);
    final ns = (s * factor).clamp(5.0, 2000.0);
    final after = _toWorld(focal, ns, _center);
    setState(() {
      _scale = ns;
      _center += Offset(before.dx - after.dx, before.dy - after.dy);
    });
  }

  Offset _toWorld(Offset p, double s, Offset c) =>
      Offset(c.dx + (p.dx - _size.width / 2) / s, c.dy - (p.dy - _size.height / 2) / s);

  @override
  Widget build(BuildContext context) {
    return AspectRatio(
      aspectRatio: widget.aspectRatio,
      child: LayoutBuilder(builder: (context, c) {
        _size = Size(c.maxWidth, c.maxHeight);
        if (_scale == null) _fit(_size);
        return ClipRRect(
          borderRadius: BorderRadius.circular(10),
          child: DecoratedBox(
            decoration: BoxDecoration(border: Border.all(color: AppColors.border), borderRadius: BorderRadius.circular(10)),
            child: Listener(
              onPointerSignal: (e) {
                if (e is PointerScrollEvent) _zoom(e.scrollDelta.dy < 0 ? 1.15 : 1 / 1.15, e.localPosition);
              },
              child: GestureDetector(
                onDoubleTap: () => setState(() => _scale = null),
                onScaleStart: (d) {
                  _startScale = _scale ?? 1;
                  _startCenter = _center;
                  _startFocal = d.localFocalPoint;
                },
                onScaleUpdate: (d) => setState(() {
                  _scale = (_startScale * d.scale).clamp(5.0, 2000.0);
                  final delta = d.localFocalPoint - _startFocal;
                  _center = Offset(_startCenter.dx - delta.dx / _scale!, _startCenter.dy + delta.dy / _scale!);
                }),
                child: Stack(fit: StackFit.expand, children: [
                  CustomPaint(
                    painter: _LidarPainter(
                      data: widget.data,
                      lagS: widget.lagS,
                      time: widget.playback.time,
                      scale: _scale!,
                      center: _center,
                      showBoxes: widget.showBoxes,
                    ),
                  ),
                  const Positioned(right: 12, bottom: 12, child: _HeightLegend()),
                  Positioned(
                    right: 12,
                    top: 10,
                    child: Text('scroll to zoom · drag to pan · double-click to reset',
                        style: TextStyle(fontSize: 10.5, color: AppColors.textSecondary.withValues(alpha: 0.8))),
                  ),
                  if (widget.hud != null) Positioned(left: 12, bottom: 12, child: widget.hud!),
                ]),
              ),
            ),
          ),
        );
      }),
    );
  }
}

class _LidarPainter extends CustomPainter {
  _LidarPainter({
    required this.data,
    required this.lagS,
    required this.time,
    required this.scale,
    required this.center,
    required this.showBoxes,
  }) : super(repaint: time);

  final LidarData data;
  final double lagS;
  final ValueListenable<double> time;
  final double scale;
  final Offset center;
  final bool showBoxes;

  static final _bgPaint = Paint()
    ..color = const Color(0xFFC9CED6)
    ..strokeWidth = 1.6
    ..strokeCap = StrokeCap.round;

  @override
  void paint(Canvas canvas, Size size) {
    final cx = size.width / 2, cy = size.height / 2;
    double sx(double u) => cx + (u - center.dx) * scale;
    double sy(double v) => cy - (v - center.dy) * scale;
    canvas.drawRect(Offset.zero & size, Paint()..color = Colors.white);

    // light metre grid
    final grid = Paint()
      ..color = const Color(0xFFEEF2F7)
      ..strokeWidth = 1;
    final u0 = (center.dx - cx / scale).floor(), u1 = (center.dx + cx / scale).ceil();
    final v0 = (center.dy - cy / scale).floor(), v1 = (center.dy + cy / scale).ceil();
    if (u1 - u0 < 200) {
      for (var u = u0; u <= u1; u++) {
        canvas.drawLine(Offset(sx(u.toDouble()), 0), Offset(sx(u.toDouble()), size.height), grid);
      }
      for (var v = v0; v <= v1; v++) {
        canvas.drawLine(Offset(0, sy(v.toDouble())), Offset(size.width, sy(v.toDouble())), grid);
      }
    }

    // background cloud, very light grey
    final bg = data.background;
    final pts = Float32List(bg.length);
    for (var i = 0; i < bg.length; i += 2) {
      pts[i] = sx(bg[i]);
      pts[i + 1] = sy(bg[i + 1]);
    }
    canvas.drawRawPoints(ui.PointMode.points, pts, _bgPaint);

    // zone footprints: 1.0 m dashed navy, 0 m and 1.7 m faint
    for (final o in data.zoneOthers) {
      _dashedPolygon(canvas, [for (final p in o) Offset(sx(p[0]), sy(p[1]))], const Color(0xFFB8C2D3), 1, 3, 4);
    }
    if (data.zone.isNotEmpty) {
      _dashedPolygon(canvas, [for (final p in data.zone) Offset(sx(p[0]), sy(p[1]))], AppColors.groundTruth, 1.6, 8, 5);
    }

    final tl = time.value + lagS; // t_lidar = t_video + lag_s
    final j = data.frameAt(tl);
    if (j == null) {
      final tp = TextPainter(
        text: const TextSpan(
            text: 'No LiDAR data at this time', style: TextStyle(color: AppColors.textSecondary, fontSize: 14)),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, Offset(cx - tp.width / 2, 34));
      return;
    }

    // foreground points coloured by height (turbo, 0..2.2 m)
    final a = data.offsets[j], b = data.offsets[j + 1];
    final counts = List<int>.filled(_bins, 0);
    final p = data.pointsCm;
    int binOf(int k) => ((p[3 * k + 2] / 100.0 / kMaxHeight).clamp(0.0, 0.9999) * _bins).floor();
    for (var k = a; k < b; k++) {
      counts[binOf(k)]++;
    }
    final buffers = [for (final c in counts) Float32List(2 * c)];
    final fill = List<int>.filled(_bins, 0);
    for (var k = a; k < b; k++) {
      final bin = binOf(k);
      final buf = buffers[bin];
      buf[fill[bin]++] = sx(p[3 * k] / 100.0);
      buf[fill[bin]++] = sy(p[3 * k + 1] / 100.0);
    }
    final pointSize = (scale * 0.035).clamp(2.2, 5.0);
    for (var i = 0; i < _bins; i++) {
      if (counts[i] == 0) continue;
      canvas.drawRawPoints(ui.PointMode.points, buffers[i], Paint()
        ..color = turbo((i + 0.5) / _bins)
        ..strokeWidth = pointSize
        ..strokeCap = StrokeCap.round);
    }

    if (!showBoxes) return;

    // short fading trail of each track (last 2 s)
    final trails = <int, List<Offset>>{};
    for (var k = j; k >= 0 && data.frames[j].t - data.frames[k].t <= 2.0; k--) {
      for (final c in data.frames[k].clusters) {
        if (c.trackId != null) (trails[c.trackId!] ??= []).add(Offset(sx(c.u), sy(c.v)));
      }
    }
    for (final pts in trails.values) {
      if (pts.length < 2) continue;
      final ordered = pts.reversed.toList();
      for (var i = 1; i < ordered.length; i++) {
        final alpha = i / ordered.length;
        canvas.drawLine(ordered[i - 1], ordered[i], Paint()
          ..color = AppColors.lidar.withValues(alpha: 0.15 + 0.6 * alpha)
          ..strokeWidth = 2.5
          ..strokeCap = StrokeCap.round);
      }
    }

    // one teal box per detected person: track ID + head height
    for (final c in data.frames[j].clusters) {
      final rect = Rect.fromLTRB(sx(c.u - c.w / 2), sy(c.v + c.d / 2), sx(c.u + c.w / 2), sy(c.v - c.d / 2));
      canvas.drawRect(rect, Paint()
        ..color = AppColors.lidar.withValues(alpha: c.confirmed ? 1 : 0.55)
        ..style = PaintingStyle.stroke
        ..strokeWidth = c.confirmed ? 2.2 : 1.4);
      final label = '${c.trackId != null ? '#${c.trackId} · ' : ''}${c.top.toStringAsFixed(2)} m';
      final tp = TextPainter(
        text: TextSpan(text: label, style: const TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.w600)),
        textDirection: TextDirection.ltr,
      )..layout();
      final lr = RRect.fromRectAndRadius(
          Rect.fromLTWH(rect.left, rect.top - tp.height - 6, tp.width + 8, tp.height + 4), const Radius.circular(3));
      canvas.drawRRect(lr, Paint()..color = AppColors.lidar.withValues(alpha: c.confirmed ? 1 : 0.6));
      tp.paint(canvas, Offset(rect.left + 4, rect.top - tp.height - 4));
    }
  }

  static void _dashedPolygon(Canvas canvas, List<Offset> pts, Color color, double width, double dash, double gap) {
    final paint = Paint()
      ..color = color
      ..strokeWidth = width;
    for (var i = 0; i < pts.length; i++) {
      final a = pts[i], b = pts[(i + 1) % pts.length];
      final len = (b - a).distance;
      if (len == 0) continue;
      final d = (b - a) / len;
      for (var pos = 0.0; pos < len; pos += dash + gap) {
        canvas.drawLine(a + d * pos, a + d * math.min(pos + dash, len), paint);
      }
    }
  }

  @override
  bool shouldRepaint(_LidarPainter old) =>
      old.data != data || old.lagS != lagS || old.scale != scale || old.center != center || old.showBoxes != showBoxes;
}

class _HeightLegend extends StatelessWidget {
  const _HeightLegend();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(8, 6, 8, 6),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.92),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('height above floor', style: TextStyle(fontSize: 10.5, color: AppColors.textSecondary)),
        const SizedBox(height: 4),
        Container(
          width: 120,
          height: 8,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(2),
            gradient: LinearGradient(colors: [for (var i = 0; i <= 10; i++) turbo(i / 10)]),
          ),
        ),
        const SizedBox(height: 2),
        const SizedBox(
          width: 120,
          child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
            Text('0', style: TextStyle(fontSize: 10, color: AppColors.textSecondary)),
            Text('1.1', style: TextStyle(fontSize: 10, color: AppColors.textSecondary)),
            Text('2.2 m', style: TextStyle(fontSize: 10, color: AppColors.textSecondary)),
          ]),
        ),
      ]),
    );
  }
}
