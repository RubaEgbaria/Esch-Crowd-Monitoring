import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:material_ui/material_ui.dart';

import '../theme.dart';

class ChartSeries {
  const ChartSeries(this.label, this.color, this.values, {this.dashed = false, this.width = 2, this.step = false});
  final String label;
  final Color color;
  final List<double?> values; // on the grid; null = no value
  final bool dashed;
  final double width;
  final bool step;
}

/// Count over time vs GT, with a playhead that follows playback. Click or drag to seek.
class CountChart extends StatelessWidget {
  const CountChart({super.key, required this.t, required this.series, required this.time, required this.onSeek,
      this.height = 220});
  final List<double> t;
  final List<ChartSeries> series;
  final ValueListenable<double> time;
  final ValueChanged<double> onSeek;
  final double height;

  static const _pad = EdgeInsets.fromLTRB(30, 10, 10, 24);

  @override
  Widget build(BuildContext context) {
    final T = t.isEmpty ? 1.0 : t.last + (t.length > 1 ? t[1] - t[0] : 0);
    double ymax = 1;
    for (final s in series) {
      for (final v in s.values) {
        if (v != null) ymax = math.max(ymax, v);
      }
    }
    ymax = (ymax + 1).ceilToDouble();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Wrap(spacing: 14, runSpacing: 4, children: [
        for (final s in series)
          Row(mainAxisSize: MainAxisSize.min, children: [
            Container(width: 16, height: s.dashed ? 2 : 3, color: s.color),
            const SizedBox(width: 6),
            Text(s.label, style: const TextStyle(fontSize: 12, color: AppColors.textSecondary)),
          ]),
      ]),
      const SizedBox(height: 8),
      SizedBox(
        height: height,
        child: LayoutBuilder(builder: (context, c) {
          final w = c.maxWidth - _pad.horizontal;
          void seek(Offset p) => onSeek(((p.dx - _pad.left) / w * T).clamp(0.0, T));
          return MouseRegion(
            cursor: SystemMouseCursors.click,
            child: GestureDetector(
              onTapDown: (d) => seek(d.localPosition),
              onHorizontalDragUpdate: (d) => seek(d.localPosition),
              child: Stack(fit: StackFit.expand, children: [
                RepaintBoundary(child: CustomPaint(painter: _SeriesPainter(t, series, T, ymax))),
                CustomPaint(painter: _Playhead(time, T)),
              ]),
            ),
          );
        }),
      ),
    ]);
  }
}

class _SeriesPainter extends CustomPainter {
  _SeriesPainter(this.t, this.series, this.T, this.ymax);
  final List<double> t;
  final List<ChartSeries> series;
  final double T, ymax;

  @override
  void paint(Canvas canvas, Size size) {
    const pad = CountChart._pad;
    final w = size.width - pad.horizontal, h = size.height - pad.vertical;
    double x(double tt) => pad.left + tt / T * w;
    double y(double v) => pad.top + h - v / ymax * h;
    final axis = Paint()
      ..color = AppColors.border
      ..strokeWidth = 1;
    final label = TextStyle(fontSize: 10.5, color: AppColors.textSecondary.withValues(alpha: 0.9));
    final yStep = ymax <= 8 ? 1 : (ymax / 6).ceil();
    for (var v = 0; v <= ymax; v += yStep) {
      canvas.drawLine(Offset(pad.left, y(v.toDouble())), Offset(pad.left + w, y(v.toDouble())), axis);
      final tp = TextPainter(text: TextSpan(text: '$v', style: label), textDirection: TextDirection.ltr)..layout();
      tp.paint(canvas, Offset(pad.left - tp.width - 6, y(v.toDouble()) - tp.height / 2));
    }
    final xStep = T > 60 ? 10 : 5;
    for (var s = 0; s <= T; s += xStep) {
      final tp = TextPainter(text: TextSpan(text: '${s}s', style: label), textDirection: TextDirection.ltr)..layout();
      tp.paint(canvas, Offset(x(s.toDouble()) - tp.width / 2, pad.top + h + 6));
    }
    for (final s in series) {
      final paint = Paint()
        ..color = s.color
        ..strokeWidth = s.width
        ..style = PaintingStyle.stroke
        ..strokeJoin = StrokeJoin.round;
      Path? path;
      final paths = <Path>[];
      for (var i = 0; i < t.length && i < s.values.length; i++) {
        final v = s.values[i];
        if (v == null) {
          if (path != null) paths.add(path);
          path = null;
          continue;
        }
        final px = x(t[i]), py = y(v);
        if (path == null) {
          path = Path()..moveTo(px, py);
        } else {
          if (s.step) {
            final prev = s.values[i - 1]!;
            path.lineTo(px, y(prev));
          }
          path.lineTo(px, py);
        }
      }
      if (path != null) paths.add(path);
      for (final p in paths) {
        if (s.dashed) {
          for (final m in p.computeMetrics()) {
            for (var d = 0.0; d < m.length; d += 9) {
              canvas.drawPath(m.extractPath(d, math.min(d + 5, m.length)), paint);
            }
          }
        } else {
          canvas.drawPath(p, paint);
        }
      }
    }
  }

  @override
  bool shouldRepaint(_SeriesPainter old) => old.series != series || old.t != t || old.ymax != ymax;
}

class _Playhead extends CustomPainter {
  _Playhead(this.time, this.T) : super(repaint: time);
  final ValueListenable<double> time;
  final double T;

  @override
  void paint(Canvas canvas, Size size) {
    const pad = CountChart._pad;
    final w = size.width - pad.horizontal;
    final px = pad.left + (time.value / T).clamp(0.0, 1.0) * w;
    canvas.drawLine(Offset(px, pad.top - 4), Offset(px, size.height - pad.bottom), Paint()
      ..color = AppColors.primary
      ..strokeWidth = 1.6);
    canvas.drawCircle(Offset(px, pad.top - 4), 3.5, Paint()..color = AppColors.primary);
  }

  @override
  bool shouldRepaint(_Playhead old) => old.T != T;
}
