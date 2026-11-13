import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/models.dart';
import '../state/providers.dart';
import '../theme.dart';
import '../util/format.dart';
import '../widgets/common.dart';
import 'count_chart.dart';
import 'hud.dart';
import 'live_controller.dart';
import 'live_models.dart';
import 'playback.dart';

const modeColors = {
  LiveMode.lidar: AppColors.lidar,
  LiveMode.camera: AppColors.yolo,
  LiveMode.fusion: AppColors.fusion,
};

/// YOLO counts on the 10 Hz grid at the current confidence (resample_counts, in the browser).
List<double> yoloGrid(YoloData y, double conf, List<double> t) {
  final ts = [for (var i = 0; i < y.frames.length; i++) i / y.fps];
  return resampleCounts(ts, y.counts(conf), t);
}

/// Count over time, metrics per mode, latency and exports. Appears once the mode has results.
class ResultsPanel extends ConsumerWidget {
  const ResultsPanel({super.key, required this.runId, required this.playback, required this.countsAt});
  final String runId;
  final PlaybackController playback;
  final CountsAt countsAt;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final st = ref.watch(liveProvider(runId));
    final r = st.result;
    if (r == null) return const SizedBox.shrink();
    return LayoutBuilder(builder: (context, c) {
      final wide = c.maxWidth >= 1000;
      final left = Column(children: [
        _LiveCountsCard(mode: st.mode, time: playback.time, countsAt: countsAt),
        const SizedBox(height: 16),
        _ChartCard(st: st, playback: playback),
      ]);
      final right = Column(children: [
        _MetricsCard(st: st),
        const SizedBox(height: 16),
        _LatencyCard(st: st),
        const SizedBox(height: 16),
        _ExportCard(runId: runId, st: st),
      ]);
      return wide
          ? Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Expanded(flex: 11, child: left),
              const SizedBox(width: 16),
              Expanded(flex: 9, child: right),
            ])
          : Column(children: [left, const SizedBox(height: 16), right]);
    });
  }
}

class _LiveCountsCard extends StatelessWidget {
  const _LiveCountsCard({required this.mode, required this.time, required this.countsAt});
  final LiveMode mode;
  final ValueListenable<double> time;
  final CountsAt countsAt;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return AppCard(
      child: ValueListenableBuilder<double>(
        valueListenable: time,
        builder: (context, now, _) {
          final c = countsAt(now);
          Widget big(String label, String value, Color color, {bool main = false}) => Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(label, style: t.bodySmall?.copyWith(color: main ? color : AppColors.textSecondary)),
                  Text(value,
                      style: TextStyle(fontSize: main ? 38 : 26, fontWeight: FontWeight.w800, color: color,
                          fontFeatures: const [FontFeature.tabularFigures()], height: 1.15)),
                ]),
              );
          final lidar = c.lidarAvailable && c.lidar != null ? '${c.lidar}' : '—';
          return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            CardTitle('Live counts', icon: Icons.groups_2_outlined, subtitle: 't = ${now.toStringAsFixed(2)} s'),
            const SizedBox(height: 14),
            Row(children: [
              if (mode == LiveMode.fusion)
                big('Fused (Stack-GBT)', c.fused == null ? '—' : c.fused!.toStringAsFixed(2), AppColors.fusion,
                    main: true),
              if (mode != LiveMode.camera) big('LiDAR', lidar, AppColors.lidar, main: mode == LiveMode.lidar),
              if (mode != LiveMode.lidar) big('YOLO', c.yolo == null ? '—' : '${c.yolo}', AppColors.yolo,
                  main: mode == LiveMode.camera),
              if (c.gt != null) big('Ground truth', c.gt!.toStringAsFixed(0), AppColors.groundTruth),
            ]),
          ]);
        },
      ),
    );
  }
}

class _ChartCard extends StatelessWidget {
  const _ChartCard({required this.st, required this.playback});
  final LiveState st;
  final PlaybackController playback;

  @override
  Widget build(BuildContext context) {
    final r = st.result!;
    final t = r.t;
    final series = <ChartSeries>[];
    final gt = r.series('gt');
    switch (st.mode) {
      case LiveMode.lidar:
        series.add(ChartSeries('LiDAR (smoothed)', AppColors.lidar, r.series('lidar')!, step: true));
      case LiveMode.camera:
        if (st.yolo != null) {
          series.add(ChartSeries('YOLO (conf > ${st.conf.toStringAsFixed(2)})', AppColors.yolo,
              yoloGrid(st.yolo!, st.conf, t), step: true));
        }
      case LiveMode.fusion:
        series.add(ChartSeries('LiDAR', AppColors.lidar.withValues(alpha: 0.35), r.series('lidar')!, width: 1.2,
            step: true));
        series.add(ChartSeries('YOLO', AppColors.yolo.withValues(alpha: 0.35), r.series('yolo')!, width: 1.2,
            step: true));
        series.add(ChartSeries('Fused (Stack-GBT, out-of-fold)', AppColors.fusion, r.series('fused')!, width: 2.4));
    }
    if (gt != null) series.add(ChartSeries('Ground truth', AppColors.groundTruth, gt, dashed: true, step: true));
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        CardTitle('Count over time', icon: Icons.show_chart,
            subtitle: '${st.mode.short} vs ground truth · click the chart to jump to that time'),
        const SizedBox(height: 12),
        CountChart(t: t, series: series, time: playback.time, onSeek: playback.seek),
      ]),
    );
  }
}

class _MetricsCard extends StatelessWidget {
  const _MetricsCard({required this.st});
  final LiveState st;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    if (!st.hasGt) {
      return const AppCard(
        child: Notice('This run has no ground truth, so there are no metrics. Add ground truth to compare the modes.',
            kind: NoticeKind.warning),
      );
    }
    // every mode run with the current parameters, side by side
    final cols = <(LiveMode, Map<String, double>, int, String)>[];
    for (final m in LiveMode.values) {
      if (!st.isCurrent(m)) continue;
      final r = st.results[m]!;
      if (m == LiveMode.camera) {
        final gt = r.series('gt');
        if (st.yolo == null || gt == null) continue;
        cols.add((m, countingMetrics(yoloGrid(st.yolo!, st.conf, r.t), [for (final g in gt) g ?? 0]), gt.length,
            'whole video, conf > ${st.conf.toStringAsFixed(2)}'));
      } else {
        final key = m == LiveMode.lidar ? 'LiDAR' : 'Fusion (Stack-GBT)';
        final mm = r.metrics[key] as Json?;
        if (mm == null) continue;
        cols.add((m, {for (final k in metricKeys) k: (mm[k] as num).toDouble()}, (mm['n'] as num).toInt(),
            mm['window'] as String));
      }
    }
    final missing = [for (final m in LiveMode.values) if (!st.isCurrent(m) && st.available(m)) m.short];
    String fmt(String k, double v) => k == 'MAE' || k == 'RMSE' || k == 'Bias' ? v.toStringAsFixed(3) : v.toStringAsFixed(1);
    final head = t.bodySmall?.copyWith(fontWeight: FontWeight.w700);
    const numStyle = TextStyle(fontSize: 13, fontFeatures: [FontFeature.tabularFigures()]);
    TableRow row(List<Widget> cells, {Color? bg}) => TableRow(
          decoration: BoxDecoration(color: bg, border: const Border(bottom: BorderSide(color: AppColors.border))),
          children: [for (final c in cells) Padding(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6), child: c)],
        );
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        const CardTitle('Metrics', icon: Icons.table_chart_outlined,
            subtitle: 'counting_metrics (sensors_fusion.ipynb) on the 10 Hz grid'),
        const SizedBox(height: 12),
        if (cols.isEmpty)
          Text('Run a mode to see its metrics.', style: t.bodySmall)
        else
          Table(
            columnWidths: const {0: FlexColumnWidth(1.5)},
            defaultColumnWidth: const FlexColumnWidth(1),
            children: [
              row([
                Text('Metric', style: head),
                for (final c in cols)
                  Text(c.$1.short, style: head?.copyWith(color: modeColors[c.$1]), textAlign: TextAlign.right),
              ]),
              for (final k in metricKeys)
                row([
                  Text(k, style: const TextStyle(fontSize: 13)),
                  for (final c in cols)
                    Text(fmt(k, c.$2[k]!), style: numStyle.copyWith(
                        fontWeight: c.$1 == st.mode ? FontWeight.w700 : FontWeight.w400), textAlign: TextAlign.right),
                ], bg: k == 'MAE' ? const Color(0xFFF7F9FC) : null),
              row([
                Text('Grid points', style: t.bodySmall),
                for (final c in cols) Text('${c.$3}', style: t.bodySmall, textAlign: TextAlign.right),
              ]),
            ],
          ),
        if (cols.isNotEmpty) ...[
          const SizedBox(height: 8),
          for (final c in cols) Text('${c.$1.short}: ${c.$4}', style: t.bodySmall),
        ],
        if (st.results[LiveMode.fusion]?.cv != null && st.isCurrent(LiveMode.fusion)) ...[
          const SizedBox(height: 6),
          Text('Stack-GBT blocked ${st.results[LiveMode.fusion]!.cv!['folds']}-fold CV MAE: '
              '${(st.results[LiveMode.fusion]!.cv!['stack_gbt_mae'] as num).toStringAsFixed(3)} '
              '± ${(st.results[LiveMode.fusion]!.cv!['stack_gbt_mae_std'] as num).toStringAsFixed(3)}',
              style: t.bodySmall),
        ],
        if (missing.isNotEmpty) ...[
          const SizedBox(height: 6),
          Text('Run ${missing.join(' and ')} with these parameters to compare.', style: t.bodySmall),
        ],
      ]),
    );
  }
}

class _LatencyCard extends StatelessWidget {
  const _LatencyCard({required this.st});
  final LiveState st;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final lat = st.result!.latency;
    final items = <(String, String, Color)>[
      if (lat['lidar_ms'] != null) ('LiDAR pipeline', '${(lat['lidar_ms'] as num).toStringAsFixed(1)} ms/frame', AppColors.lidar),
      if (lat['yolo_ms'] != null) ('YOLO11m', '${(lat['yolo_ms'] as num).toStringAsFixed(0)} ms/frame', AppColors.yolo),
      if (lat['fusion_fit_s'] != null)
        ('Stack-GBT (5 folds)', '${(lat['fusion_fit_s'] as num).toStringAsFixed(2)} s to fit', AppColors.fusion),
    ];
    final device = (st.result!.json['yolo_summary'] as Json?)?['device'];
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        CardTitle('Mean latency', icon: Icons.timer_outlined, subtitle: device == null ? null : 'YOLO on $device'),
        const SizedBox(height: 10),
        for (final (label, value, color) in items)
          Padding(
            padding: const EdgeInsets.only(bottom: 4),
            child: Row(children: [
              Container(width: 8, height: 8, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
              const SizedBox(width: 8),
              Expanded(child: Text(label, style: t.bodyMedium)),
              Text(value, style: t.bodyMedium?.copyWith(fontWeight: FontWeight.w600,
                  fontFeatures: const [FontFeature.tabularFigures()])),
            ]),
          ),
      ]),
    );
  }
}

class _ExportCard extends ConsumerStatefulWidget {
  const _ExportCard({required this.runId, required this.st});
  final String runId;
  final LiveState st;

  @override
  ConsumerState<_ExportCard> createState() => _ExportCardState();
}

class _ExportCardState extends ConsumerState<_ExportCard> {
  bool _roi = true;

  @override
  Widget build(BuildContext context) {
    final st = widget.st;
    final api = ref.read(apiProvider);
    final ctl = ref.read(liveProvider(widget.runId).notifier);
    final t = Theme.of(context).textTheme;
    final current = st.isCurrent(st.mode);
    final job = st.liveJob;
    final exporting = job != null && job.kind == 'export' && job.active;
    final last = st.run?.lastExport;
    void open(String url) => launchUrl(Uri.parse(url), webOnlyWindowName: '_blank');
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        CardTitle('Export', icon: Icons.download_outlined, subtitle: '${st.mode.short} · per-frame results on the 10 Hz grid'),
        const SizedBox(height: 12),
        Wrap(spacing: 8, runSpacing: 8, children: [
          OutlinedButton.icon(
            onPressed: current ? () => open(api.exportResultsUrl(widget.runId, st.mode.key, 'csv', st.params)) : null,
            icon: const Icon(Icons.table_view_outlined, size: 18),
            label: const Text('CSV'),
          ),
          OutlinedButton.icon(
            onPressed: current ? () => open(api.exportResultsUrl(widget.runId, st.mode.key, 'json', st.params)) : null,
            icon: const Icon(Icons.data_object, size: 18),
            label: const Text('JSON'),
          ),
        ]),
        const SizedBox(height: 14),
        Row(children: [
          Expanded(
            child: FilledButton.icon(
              onPressed: current && !st.busy ? () => ctl.exportVideo(roi: _roi && st.mode != LiveMode.lidar) : null,
              icon: const Icon(Icons.movie_outlined, size: 18),
              label: const Text('Export annotated video'),
            ),
          ),
        ]),
        if (st.mode != LiveMode.lidar)
          CheckboxListTile(
            value: _roi,
            onChanged: (v) => setState(() => _roi = v ?? true),
            dense: true,
            contentPadding: EdgeInsets.zero,
            controlAffinity: ListTileControlAffinity.leading,
            title: Text('Include the ROI (approximate calibration)', style: t.bodySmall),
          ),
        if (!current)
          Text('Run this mode with the current parameters to export.', style: t.bodySmall),
        if (exporting) ...[
          const SizedBox(height: 10),
          JobProgress(job, showOverall: false),
        ],
        if (!exporting && last != null) ...[
          const SizedBox(height: 10),
          Notice(
            '${last['file']} · ${formatBytes(last['size'] as num?)}',
            title: 'Annotated video ready (${last['mode']})',
            action: TextButton(
              onPressed: () => open(api.exportFileUrl(widget.runId, last['file'] as String)),
              child: const Text('Download'),
            ),
          ),
        ],
      ]),
    );
  }
}
