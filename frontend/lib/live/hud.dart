import 'package:flutter/foundation.dart';
import 'package:material_ui/material_ui.dart';

import '../theme.dart';
import 'live_models.dart';

/// Counts of the active mode at time t (what the HUD and the side panel show).
class LiveCounts {
  const LiveCounts({required this.t, this.gt, this.lidar, this.yolo, this.fused, this.lidarAvailable = true});
  final double t;
  final double? gt;
  final int? lidar; // smoothed LiDAR count of the frame shown
  final int? yolo; // YOLO boxes shown in this frame
  final double? fused; // Stack-GBT out-of-fold prediction (10 Hz grid)
  final bool lidarAvailable;
}

typedef CountsAt = LiveCounts Function(double t);

// Lighter tints of the source colours, readable on the dark HUD panel.
const _hudLidar = Color(0xFF5EEAD4);
const _hudYolo = Color(0xFF86EFAC);
const _hudFused = Color(0xFFC7D2FE);

/// The HUD of the notebook's fusion_demo (draw_hud): t, GT and the counts of the active mode only.
class Hud extends StatelessWidget {
  const Hud({super.key, required this.mode, required this.time, required this.countsAt});
  final LiveMode mode;
  final ValueListenable<double> time;
  final CountsAt countsAt;

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<double>(
      valueListenable: time,
      builder: (context, t, _) {
        final c = countsAt(t);
        String n(num? v, [int d = 0]) => v == null ? '—' : v.toStringAsFixed(d);
        final rows = <(String, String, Color)>[
          ('t', '${t.toStringAsFixed(2)} s', Colors.white),
          if (c.gt != null) ('GT', n(c.gt), Colors.white),
          if (mode != LiveMode.camera) ('LiDAR', c.lidarAvailable ? n(c.lidar) : 'no data', _hudLidar),
          if (mode != LiveMode.lidar) ('YOLO', n(c.yolo), _hudYolo),
          if (mode == LiveMode.fusion) ('FUSED', n(c.fused, 1), _hudFused),
        ];
        return Container(
          padding: const EdgeInsets.fromLTRB(10, 7, 12, 7),
          decoration: BoxDecoration(color: const Color(0xC70B1220), borderRadius: BorderRadius.circular(8)),
          child: DefaultTextStyle(
            style: const TextStyle(fontFeatures: [FontFeature.tabularFigures()], fontSize: 13, height: 1.45),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
              for (final (label, value, color) in rows)
                Row(mainAxisSize: MainAxisSize.min, children: [
                  SizedBox(width: 52, child: Text(label, style: TextStyle(color: color.withValues(alpha: 0.85)))),
                  Text(value, style: TextStyle(color: color, fontWeight: FontWeight.w700)),
                ]),
            ]),
          ),
        );
      },
    );
  }
}

/// The fused Stack-GBT count, large, above the two views (Fusion mode).
class FusedBanner extends StatelessWidget {
  const FusedBanner({super.key, required this.time, required this.countsAt});
  final ValueListenable<double> time;
  final CountsAt countsAt;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return ValueListenableBuilder<double>(
      valueListenable: time,
      builder: (context, now, _) {
        final c = countsAt(now);
        Widget small(String label, String value, Color color) => Padding(
              padding: const EdgeInsets.only(left: 28),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(label, style: t.bodySmall),
                Text(value, style: t.titleLarge?.copyWith(color: color, fontFeatures: const [FontFeature.tabularFigures()])),
              ]),
            );
        return Container(
          padding: const EdgeInsets.fromLTRB(18, 12, 18, 12),
          decoration: BoxDecoration(
            color: const Color(0xFFF5F4FE),
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: AppColors.fusion.withValues(alpha: 0.25)),
          ),
          child: Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
            Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Fused count · Stack-GBT (out-of-fold)', style: t.bodySmall?.copyWith(color: AppColors.fusion)),
              Row(crossAxisAlignment: CrossAxisAlignment.baseline, textBaseline: TextBaseline.alphabetic, children: [
                Text(c.fused == null ? '—' : c.fused!.toStringAsFixed(2),
                    style: const TextStyle(fontSize: 40, fontWeight: FontWeight.w800, color: AppColors.fusion,
                        fontFeatures: [FontFeature.tabularFigures()], height: 1.1)),
                const SizedBox(width: 8),
                Text(c.fused == null ? 'no LiDAR at this time' : 'people  (≈ ${c.fused!.round()})',
                    style: t.titleMedium?.copyWith(color: AppColors.fusion)),
              ]),
            ]),
            const Spacer(),
            if (c.gt != null) small('Ground truth', c.gt!.toStringAsFixed(0), AppColors.groundTruth),
            small('LiDAR', c.lidarAvailable && c.lidar != null ? '${c.lidar}' : '—', AppColors.lidar),
            small('YOLO', c.yolo == null ? '—' : '${c.yolo}', AppColors.yolo),
          ]),
        );
      },
    );
  }
}
