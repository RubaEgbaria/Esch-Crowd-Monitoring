import 'package:material_ui/material_ui.dart';

import '../api/models.dart';
import '../theme.dart';
import '../util/format.dart';
import 'common.dart';

/// Compact summary of a processed run (the full Results screen comes in Phase 4).
class ResultsSummary extends StatelessWidget {
  const ResultsSummary(this.run, {super.key});
  final Run run;

  @override
  Widget build(BuildContext context) {
    final r = run.results!;
    final al = (r['alignment'] as Json?) ?? const {};
    final lid = (r['lidar'] as Json?) ?? const {};
    final yolo = (r['yolo'] as Json?) ?? const {};
    final fusion = (r['fusion'] as Json?) ?? const {};
    final metrics = [for (final m in (r['metrics'] as List? ?? const [])) m as Json];
    final timings = (r['timings'] as Json?) ?? const {};

    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        CardTitle('Processing results', icon: Icons.insights,
            subtitle: 'Total ${formatSeconds(timings.values.fold<num>(0, (a, v) => a + (v as num)), digits: 1)}'
                ' · ${timings.entries.map((e) => '${e.key} ${formatSeconds(e.value as num, digits: 1)}').join(' · ')}'),
        const SizedBox(height: 20),
        _Section('Time alignment', child: _Alignment(al)),
        const SizedBox(height: 20),
        _Section('Sensors', child: Wrap(spacing: 12, runSpacing: 12, children: [
          _SensorTile(
            color: AppColors.lidar,
            icon: Icons.radar,
            title: 'LiDAR (Qb2)',
            lines: [
              '${lid['frames']} frames · ${lid['rate_hz']} Hz · ${formatSeconds(lid['duration_s'] as num?)}',
              'mean ${(lid['latency_ms_mean'] as num?)?.toStringAsFixed(1)} ms/frame',
              'mean count raw ${lid['raw_mean']} · tracked ${lid['tracked_mean']} · smoothed ${lid['smooth_mean']}',
            ],
          ),
          _SensorTile(
            color: AppColors.yolo,
            icon: Icons.videocam_outlined,
            title: 'YOLO11m (camera)',
            lines: [
              '${yolo['frames']} frames · ${(yolo['fps'] as num?)?.toStringAsFixed(2)} fps · ${yolo['device']}',
              'mean ${(yolo['latency_ms_mean'] as num?)?.toStringAsFixed(0)} ms/frame · imgsz ${yolo['imgsz']}',
              'boxes stored at conf > ${yolo['stored_conf']} · counted at conf > ${al['yolo_conf']}',
            ],
          ),
        ])),
        const SizedBox(height: 20),
        _Section('Fusion', child: _FusionTable(fusion)),
        if (metrics.isNotEmpty) ...[
          const SizedBox(height: 20),
          _Section('Counting metrics', child: _MetricsTable(metrics, auto: fusion['auto'] as String?)),
        ],
      ]),
    );
  }
}

class _Section extends StatelessWidget {
  const _Section(this.title, {required this.child});
  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text(title.toUpperCase(),
            style: Theme.of(context).textTheme.bodySmall?.copyWith(fontWeight: FontWeight.w700, letterSpacing: 0.6)),
        const SizedBox(height: 10),
        child,
      ]);
}

class _Alignment extends StatelessWidget {
  const _Alignment(this.al);
  final Json al;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final lag = al['lag_s'] as num?;
    final r = al['r'] as num?;
    final window = al['window'] as List?;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Wrap(spacing: 28, runSpacing: 12, children: [
        _Stat('LiDAR lag', lag == null ? '—' : '${lag >= 0 ? '+' : '−'}${lag.abs().toStringAsFixed(2)} s',
            sub: al['manual'] == true ? 'manual offset' : 'cross-correlation, ±${al['max_lag_s']} s'),
        _Stat('Correlation r', r == null ? '—' : r.toStringAsFixed(2), sub: 'YOLO vs LiDAR counts'),
        _Stat('Video', formatSeconds(al['T'] as num?), sub: '${al['n_grid']} grid points at ${al['grid_hz']} Hz'),
        _Stat('LiDAR recording', formatSeconds(al['lidar_duration_s'] as num?),
            sub: window == null ? 'no overlap' : 'covers ${(window[0] as num).toStringAsFixed(2)}–${(window[1] as num).toStringAsFixed(2)} s'),
      ]),
      const SizedBox(height: 12),
      Text(
        'LiDAR timestamps are shifted by the lag (t_video = t_lidar − lag). The LiDAR covers '
        '${al['n_window']} of ${al['n_grid']} grid points; the others have no LiDAR value (nothing is wrapped or invented). '
        'Fusion and metrics use the overlap.',
        style: t.bodySmall,
      ),
      if (al['at_edge'] == true) ...[
        const SizedBox(height: 10),
        Notice(
          'The best lag is at the edge of the ±${al['max_lag_s']} s search window, so the true offset may be larger. '
          'The notebook default (±5 s) is kept.',
          kind: NoticeKind.warning,
        ),
      ],
      if (al['note'] != null) ...[
        const SizedBox(height: 10),
        Notice(al['note'] as String, kind: NoticeKind.warning),
      ],
    ]);
  }
}

class _Stat extends StatelessWidget {
  const _Stat(this.label, this.value, {this.sub});
  final String label;
  final String value;
  final String? sub;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(label, style: t.bodySmall),
      Text(value, style: t.titleLarge?.copyWith(fontFeatures: const [FontFeature.tabularFigures()])),
      if (sub != null) Text(sub!, style: t.bodySmall),
    ]);
  }
}

class _SensorTile extends StatelessWidget {
  const _SensorTile({required this.color, required this.icon, required this.title, required this.lines});
  final Color color;
  final IconData icon;
  final String title;
  final List<String> lines;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Container(
      constraints: const BoxConstraints(minWidth: 320, maxWidth: 520),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppColors.border),
        color: color.withValues(alpha: 0.04),
      ),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(icon, color: color, size: 20),
        const SizedBox(width: 10),
        Flexible(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: t.titleSmall?.copyWith(color: color)),
            const SizedBox(height: 4),
            for (final l in lines) Text(l, style: t.bodySmall?.copyWith(color: AppColors.text)),
          ]),
        ),
      ]),
    );
  }
}

class _FusionTable extends StatelessWidget {
  const _FusionTable(this.f);
  final Json f;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final table = [for (final r in (f['table'] as List? ?? const [])) r as Json];
    if (table.isEmpty) {
      return Notice((f['note'] as String?) ?? 'Only the Mean fusion is available.', kind: NoticeKind.warning);
    }
    final auto = f['auto'] as String?;
    TableRow row(List<Widget> cells, {Color? bg}) => TableRow(
          decoration: BoxDecoration(color: bg, border: const Border(bottom: BorderSide(color: AppColors.border))),
          children: [for (final c in cells) Padding(padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8), child: c)],
        );
    final head = t.bodySmall?.copyWith(fontWeight: FontWeight.w700);
    const numStyle = TextStyle(fontFeatures: [FontFeature.tabularFigures()], fontSize: 13.5);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Text(
        'Blocked ${f['folds']}-fold cross-validation on the ${f['n']} grid points where both sensors overlap '
        '(out-of-fold predictions only). Auto = the lowest MAE: $auto.',
        style: t.bodySmall,
      ),
      const SizedBox(height: 10),
      if (f['note'] != null) ...[Notice(f['note'] as String, kind: NoticeKind.warning), const SizedBox(height: 10)],
      SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: ConstrainedBox(
          constraints: const BoxConstraints(minWidth: 560),
          child: Table(
            columnWidths: const {0: FlexColumnWidth(2.2), 1: FlexColumnWidth(1), 2: FlexColumnWidth(1), 3: FlexColumnWidth(1)},
            children: [
              row([Text('Method', style: head), Text('MAE', style: head), Text('± std', style: head), Text('RMSE', style: head)]),
              for (final r in table)
                row([
                  Row(children: [
                    Container(
                      width: 8, height: 8, margin: const EdgeInsets.only(right: 8),
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: switch (r['method']) {
                          'LiDAR only' => AppColors.lidar,
                          'YOLO only' => AppColors.yolo,
                          _ => AppColors.fusion,
                        },
                      ),
                    ),
                    Flexible(child: Text('${r['method']}', style: TextStyle(
                        fontWeight: r['method'] == auto ? FontWeight.w700 : FontWeight.w500, fontSize: 13.5))),
                    if (r['method'] == auto) ...[
                      const SizedBox(width: 8),
                      const Pill('Auto', color: AppColors.fusion, background: Color(0xFFEEEDFD)),
                    ],
                  ]),
                  Text((r['mae'] as num).toStringAsFixed(3), style: numStyle),
                  Text((r['mae_std'] as num).toStringAsFixed(3), style: numStyle),
                  Text((r['rmse'] as num).toStringAsFixed(3), style: numStyle),
                ], bg: r['method'] == auto ? const Color(0xFFF6F5FE) : null),
            ],
          ),
        ),
      ),
    ]);
  }
}

class _MetricsTable extends StatelessWidget {
  const _MetricsTable(this.rows, {this.auto});
  final List<Json> rows;
  final String? auto;

  static const cols = ['Precision', 'Recall', 'F1 Score', 'MAE', 'RMSE', 'Bias', 'Exact %', 'Within ±1 %'];

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final head = t.bodySmall?.copyWith(fontWeight: FontWeight.w700);
    const numStyle = TextStyle(fontFeatures: [FontFeature.tabularFigures()], fontSize: 13);
    TableRow row(List<Widget> cells, {Color? bg}) => TableRow(
          decoration: BoxDecoration(color: bg, border: const Border(bottom: BorderSide(color: AppColors.border))),
          children: [for (final c in cells) Padding(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 7), child: c)],
        );
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Text('counting_metrics (sensors_fusion.ipynb) on the overlap; the last row is YOLO over the whole video.',
          style: t.bodySmall),
      const SizedBox(height: 10),
      SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: ConstrainedBox(
          constraints: const BoxConstraints(minWidth: 900),
          child: Table(
            columnWidths: const {0: FlexColumnWidth(2.2)},
            defaultColumnWidth: const FlexColumnWidth(1),
            children: [
              row([Text('Method', style: head), for (final c in cols) Text(c, style: head)]),
              for (final m in rows)
                row([
                  Text('${m['method']}', style: TextStyle(
                      fontSize: 13, fontWeight: m['method'] == auto ? FontWeight.w700 : FontWeight.w500)),
                  for (final c in cols)
                    Text(m[c] is num ? (m[c] as num).toStringAsFixed(c.contains('%') || c == 'Precision' || c == 'Recall' || c == 'F1 Score' ? 1 : 2) : '—',
                        style: numStyle),
                ], bg: m['method'] == auto ? const Color(0xFFF6F5FE) : null),
            ],
          ),
        ),
      ),
    ]);
  }
}
