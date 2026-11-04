import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../state/providers.dart';
import '../theme.dart';
import '../util/format.dart';
import '../widgets/common.dart';

class RunsScreen extends ConsumerWidget {
  const RunsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final runs = ref.watch(runsProvider);
    final t = Theme.of(context).textTheme;

    return AppShell(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Runs', style: t.headlineSmall),
              const SizedBox(height: 4),
              Text('Recorded sessions: a Qb2 LiDAR recording and a camera video of the same scene.',
                  style: t.bodyMedium?.copyWith(color: AppColors.textSecondary)),
            ]),
          ),
          const SizedBox(width: 16),
          FilledButton.icon(
            onPressed: () => context.go('/new'),
            icon: const Icon(Icons.add, size: 20),
            label: const Text('New run'),
          ),
        ]),
        const SizedBox(height: 24),
        runs.when(
          skipLoadingOnRefresh: true,
          loading: () => const Padding(
            padding: EdgeInsets.all(48),
            child: Center(child: CircularProgressIndicator()),
          ),
          error: (e, _) => AppCard(
            child: Notice(
              e.toString(),
              kind: NoticeKind.error,
              title: e is ApiException && e.offline ? 'Backend not reachable' : 'Could not load the runs',
              action: TextButton(onPressed: () => ref.invalidate(runsProvider), child: const Text('Retry')),
            ),
          ),
          data: (list) => list.isEmpty
              ? const _EmptyState()
              : Column(children: [
                  for (final r in list) ...[_RunCard(r), const SizedBox(height: 12)],
                ]),
        ),
      ]),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState();

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return AppCard(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 48),
      child: Column(children: [
        Container(
          width: 56,
          height: 56,
          decoration: const BoxDecoration(color: AppColors.primaryTint, shape: BoxShape.circle),
          child: const Icon(Icons.folder_open_outlined, color: AppColors.primary, size: 28),
        ),
        const SizedBox(height: 16),
        Text('No runs yet', style: t.titleLarge),
        const SizedBox(height: 6),
        Text(
          'Create a run from a Google Drive folder, or upload the Qb2 .zip and the camera video.',
          textAlign: TextAlign.center,
          style: t.bodyMedium?.copyWith(color: AppColors.textSecondary),
        ),
        const SizedBox(height: 20),
        FilledButton.icon(
          onPressed: () => context.go('/new'),
          icon: const Icon(Icons.add, size: 20),
          label: const Text('New run'),
        ),
      ]),
    );
  }
}

class _RunCard extends ConsumerWidget {
  const _RunCard(this.run);
  final Run run;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = Theme.of(context).textTheme;
    final step = run.job?.currentStep;
    final source = run.isDrive
        ? 'Google Drive${(run.source['path'] as String?)?.isNotEmpty == true ? ' · ${run.source['path']}' : ''}'
        : 'Uploaded files';
    final gt = run.groundTruth;
    final cam = run.check(roleCameraVideo)?.info;
    final lidar = run.check(roleLidarZip)?.info;
    final Map<String, dynamic>? results = run.results;

    return AppCard(
      padding: const EdgeInsets.fromLTRB(20, 16, 12, 16),
      child: InkWell(
        borderRadius: BorderRadius.circular(kRadius),
        onTap: () => context.go('/runs/${run.id}'),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(color: AppColors.primaryTint, borderRadius: BorderRadius.circular(10)),
            child: Icon(run.isDrive ? Icons.add_to_drive : Icons.upload_file, color: AppColors.primary, size: 21),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Flexible(child: Text(run.name, style: t.titleMedium, overflow: TextOverflow.ellipsis)),
                const SizedBox(width: 10),
                StatusPill(run),
              ]),
              const SizedBox(height: 3),
              Text('${formatDateTime(run.createdAt)}  ·  $source',
                  style: t.bodySmall, maxLines: 1, overflow: TextOverflow.ellipsis),
              const SizedBox(height: 10),
              Wrap(spacing: 8, runSpacing: 6, children: [
                Pill('${run.files.length} files · ${formatBytes(run.totalSize)}', icon: Icons.insert_drive_file_outlined),
                if (lidar?['frames'] != null)
                  Pill('LiDAR ${lidar!['frames']} frames', color: AppColors.lidar,
                      background: AppColors.lidar.withValues(alpha: 0.08)),
                if (cam?['duration_s'] != null)
                  Pill('Video ${formatSeconds(cam!['duration_s'] as num, digits: 1)}', icon: Icons.videocam_outlined),
                Pill(
                  gt == null
                      ? 'No ground truth'
                      : 'Ground truth${gt.preset != null ? ': ${gt.preset}' : ''} · ${gt.segments.length} segments',
                  icon: Icons.flag_outlined,
                ),
                if (results?['alignment']?['lag_s'] is num)
                  Pill('lag ${(results!['alignment']['lag_s'] as num).toStringAsFixed(2)} s', icon: Icons.sync_alt),
                if (results?['fusion']?['auto'] != null && (results!['fusion']['table'] as List?)?.isNotEmpty == true)
                  Pill('Fusion: ${results['fusion']['auto']}', color: AppColors.fusion,
                      background: AppColors.fusion.withValues(alpha: 0.08)),
              ]),
              if (run.active && run.job != null) ...[
                const SizedBox(height: 12),
                Row(children: [
                  Expanded(
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(99),
                      child: LinearProgressIndicator(value: run.job!.progress ?? 0, minHeight: 5),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Text(
                    [
                      if (step != null) step.label,
                      '${((run.job!.progress ?? 0) * 100).round()}%',
                      if (run.job!.etaS != null) formatEtaShort(run.job!.etaS),
                    ].join(' · '),
                    style: t.bodySmall,
                  ),
                ]),
              ],
              if (run.status == 'error' && run.error != null) ...[
                const SizedBox(height: 10),
                Text(run.error!, style: t.bodySmall?.copyWith(color: AppColors.error)),
              ],
              if (run.status == 'interrupted' && run.error != null) ...[
                const SizedBox(height: 10),
                Text(run.error!, style: t.bodySmall),
              ],
            ]),
          ),
          const SizedBox(width: 8),
          _RunActions(run),
        ]),
      ),
    );
  }
}

class _RunActions extends ConsumerWidget {
  const _RunActions(this.run);
  final Run run;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Row(mainAxisSize: MainAxisSize.min, children: [
      TextButton(onPressed: () => context.go('/runs/${run.id}'), child: const Text('Open')),
      IconButton(
        tooltip: run.active ? 'Already running' : (run.status == 'ready' ? 'Analyze' : 'Rerun (cached steps are reused)'),
        onPressed: run.active
            ? null
            : () async {
                try {
                  await ref.read(runsProvider.notifier).rerun(run.id);
                } on ApiException catch (e) {
                  if (context.mounted) showError(context, e);
                }
              },
        icon: const Icon(Icons.replay, size: 20),
      ),
      IconButton(
        tooltip: 'Delete run',
        onPressed: () => deleteRunFlow(context, ref, run),
        icon: const Icon(Icons.delete_outline, size: 20),
      ),
    ]);
  }
}

Future<bool> deleteRunFlow(BuildContext context, WidgetRef ref, Run run) async {
  final ok = await confirmDialog(
    context,
    title: 'Delete "${run.name}"?',
    message: 'This removes its files from data/runs/ and its results from cache/ on this laptop. '
        '${run.isDrive ? 'The files on Google Drive are not touched.' : 'You would need to upload the files again.'}',
    confirmLabel: 'Delete',
    destructive: true,
  );
  if (!ok) return false;
  try {
    await ref.read(runsProvider.notifier).delete(run.id);
    return true;
  } on ApiException catch (e) {
    if (context.mounted) showError(context, e);
    return false;
  }
}
