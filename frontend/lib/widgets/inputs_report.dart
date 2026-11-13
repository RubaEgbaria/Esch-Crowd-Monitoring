import 'package:material_ui/material_ui.dart';

import '../api/models.dart';
import '../theme.dart';
import '../util/format.dart';
import 'common.dart';

/// Files of a run with what validation found in each of them.
class InputsReport extends StatelessWidget {
  const InputsReport(this.run, {super.key});
  final Run run;

  @override
  Widget build(BuildContext context) {
    final files = run.files;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      for (final role in allRoles)
        if (files[role] != null) ...[
          _FileRow(role: role, file: files[role]!, report: run.check(role)),
          const SizedBox(height: 14),
        ],
      if (run.groundTruth != null) _GtReport(run),
    ]);
  }
}

class _FileRow extends StatelessWidget {
  const _FileRow({required this.role, required this.file, required this.report});
  final String role;
  final RunFile file;
  final CheckReport? report;

  String _facts() {
    final i = report?.info ?? const {};
    if (i.isEmpty) return '';
    if (role == roleLidarZip) {
      final zone = i['zone'] as Map?;
      final empty = (i['frames_empty'] as num?) ?? 0;
      final failed = (i['frames_failed'] as num?) ?? 0;
      return [
        if (i['frames'] != null) '${i['frames']} frames',
        if (empty > 0) '$empty empty',
        if (failed > 0) '$failed skipped',
        if (i['points_min'] != null)
          '${formatInt(i['points_min'] as num)}–${formatInt(i['points_max'] as num)} pts/frame',
        if (i['duration_s'] != null) formatSeconds(i['duration_s'] as num),
        if (i['rate_hz'] != null) '${i['rate_hz']} Hz',
        if (i['background_points'] != null) 'background ${formatInt(i['background_points'] as num)} pts',
        if (zone != null)
          "zone '${zone['name']}' ${(zone['size'] as List)[0]} × ${(zone['size'] as List)[1]} m",
      ].join('  ·  ');
    }
    return [
      if (i['width'] != null) '${i['width']} × ${i['height']}',
      if (i['fps'] != null) '${i['fps']} fps',
      if (i['frames'] != null) '${i['frames']} frames',
      if (i['duration_s'] != null) formatSeconds(i['duration_s'] as num),
      if ((i['codec'] as String?)?.isNotEmpty == true) 'codec ${i['codec']}',
    ].join('  ·  ');
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final r = report;
    final color = role == roleLidarZip ? AppColors.lidar : AppColors.primary;
    final icon = switch (role) {
      roleLidarZip => Icons.radar,
      roleCameraVideo => Icons.videocam_outlined,
      _ => Icons.ondemand_video_outlined,
    };
    final facts = _facts();
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Container(
        width: 34,
        height: 34,
        decoration: BoxDecoration(color: color.withValues(alpha: 0.09), borderRadius: BorderRadius.circular(8)),
        child: Icon(icon, size: 19, color: color),
      ),
      const SizedBox(width: 12),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Text(roleLabels[role]!, style: t.bodySmall?.copyWith(fontWeight: FontWeight.w600)),
            const SizedBox(width: 8),
            if (r != null)
              r.ok
                  ? const Pill('Valid', color: AppColors.primary, background: AppColors.primaryTint, icon: Icons.check)
                  : const Pill('Invalid', color: AppColors.error, background: AppColors.errorTint, icon: Icons.close),
          ]),
          const SizedBox(height: 2),
          Text('${file.name}  ·  ${formatBytes(file.size)}', style: t.bodyMedium?.copyWith(fontWeight: FontWeight.w500)),
          if (facts.isNotEmpty) Text(facts, style: t.bodySmall),
          if (r != null)
            for (final e in r.errors)
              Padding(padding: const EdgeInsets.only(top: 6), child: Notice(e, kind: NoticeKind.error)),
          if (r != null)
            for (final w in r.warnings)
              Padding(padding: const EdgeInsets.only(top: 6), child: Notice(w, kind: NoticeKind.warning)),
        ]),
      ),
    ]);
  }
}

class _GtReport extends StatelessWidget {
  const _GtReport(this.run);
  final Run run;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final gt = run.groundTruth!;
    final report = run.check('ground_truth');
    final resolved = (report?.json['resolved'] as List?)?.cast<Map<String, dynamic>>();
    final total = report?.json['T'] as num?;
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Container(
        width: 34,
        height: 34,
        decoration: BoxDecoration(color: AppColors.neutralTint, borderRadius: BorderRadius.circular(8)),
        child: const Icon(Icons.flag_outlined, size: 19, color: AppColors.groundTruth),
      ),
      const SizedBox(width: 12),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Ground truth${gt.preset != null ? ' · ${gt.preset}' : ''}',
              style: t.bodySmall?.copyWith(fontWeight: FontWeight.w600)),
          const SizedBox(height: 4),
          Wrap(spacing: 8, runSpacing: 6, children: [
            for (var i = 0; i < gt.segments.length; i++)
              Pill(
                resolved != null && i < resolved.length
                    ? '${formatToken(gt.segments[i].start)}–${formatToken(gt.segments[i].end)}  '
                        '(${(resolved[i]['start'] as num).toStringAsFixed(2)}–${(resolved[i]['end'] as num).toStringAsFixed(2)} s): '
                        '${gt.segments[i].people} people'
                    : '${formatToken(gt.segments[i].start)}–${formatToken(gt.segments[i].end)}: ${gt.segments[i].people} people',
                color: AppColors.text,
              ),
          ]),
          if (total != null) ...[
            const SizedBox(height: 4),
            Text('T = ${total.toStringAsFixed(2)} s (video duration)', style: t.bodySmall),
          ],
          if (report != null && report.json['constant'] == true)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: const Notice(
                'The ground truth is constant over the whole run, so learned fusion is trivial here.',
                kind: NoticeKind.warning,
              ),
            ),
          if (report != null)
            for (final e in report.errors)
              Padding(padding: const EdgeInsets.only(top: 6), child: Notice(e, kind: NoticeKind.error)),
          if (report != null)
            for (final w in report.warnings)
              Padding(padding: const EdgeInsets.only(top: 6), child: Notice(w, kind: NoticeKind.warning)),
        ]),
      ),
    ]);
  }
}
