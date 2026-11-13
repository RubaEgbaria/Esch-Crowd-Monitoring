import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../state/providers.dart';
import '../theme.dart';
import '../util/format.dart';
import '../widgets/common.dart';
import '../widgets/inputs_report.dart';
import '../widgets/results_summary.dart';
import 'runs_screen.dart' show deleteRunFlow;

/// One run: device, Analyze, live progress, processing results, inputs.
/// The page polls the backend while the run is active, so it updates live and
/// shows the current progress when reopened (the job runs on the backend).
class RunDetailScreen extends ConsumerWidget {
  const RunDetailScreen({super.key, required this.runId});
  final String runId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final runAsync = ref.watch(runProvider(runId));
    final t = Theme.of(context).textTheme;

    return AppShell(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: () => context.go('/'),
            icon: const Icon(Icons.arrow_back, size: 18),
            label: const Text('Runs'),
          ),
        ),
        const SizedBox(height: 4),
        runAsync.when(
          skipLoadingOnRefresh: true,
          loading: () => const Padding(padding: EdgeInsets.all(48), child: Center(child: CircularProgressIndicator())),
          error: (e, _) => AppCard(
            child: Notice(
              e.toString(),
              kind: NoticeKind.error,
              title: e is ApiException && e.status == 404 ? 'Run not found' : 'Could not load the run',
            ),
          ),
          data: (run) => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
                    Text(run.name, style: t.headlineSmall),
                    StatusPill(run),
                    const _DeviceBadge(),
                  ]),
                  const SizedBox(height: 4),
                  Text(
                    '${formatDateTime(run.createdAt)}  ·  '
                    '${run.isDrive ? 'Google Drive · ${run.source['path'] ?? ''}' : 'Uploaded files'}  ·  ${run.id}',
                    style: t.bodySmall,
                  ),
                ]),
              ),
              const SizedBox(width: 12),
              _Actions(run),
            ]),
            const SizedBox(height: 20),
            if (run.status == 'ready' && !run.active) ...[
              _AnalyzeCallout(run),
              const SizedBox(height: 20),
            ],
            if (run.job != null && (run.active || run.results == null || run.status == 'error')) ...[
              _ProgressCard(run),
              const SizedBox(height: 20),
            ],
            if (run.results != null && !run.active) ...[
              ResultsSummary(run),
              const SizedBox(height: 20),
            ],
            AppCard(
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                CardTitle(
                  'Inputs',
                  icon: Icons.fact_check_outlined,
                  subtitle: run.validation == null
                      ? 'Not checked yet.'
                      : 'Checked ${formatDateTime(run.validation!['checked_at'] as String?)}',
                ),
                const SizedBox(height: 16),
                InputsReport(run),
              ]),
            ),
            const SizedBox(height: 20),
            _ViewsCard(run),
            if (run.job != null && run.results != null && !run.active && run.status != 'error') ...[
              const SizedBox(height: 20),
              AppCard(
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  const CardTitle('Last processing', icon: Icons.timeline),
                  const SizedBox(height: 16),
                  JobProgress(run.job!),
                ]),
              ),
            ],
          ]),
        ),
      ]),
    );
  }
}

class _DeviceBadge extends ConsumerWidget {
  const _DeviceBadge();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final sys = ref.watch(systemProvider);
    return sys.when(
      loading: () => const Pill('Detecting device…', icon: Icons.memory),
      error: (_, _) => const SizedBox.shrink(),
      data: (s) => Tooltip(
        message: s.error ?? 'YOLO runs on this device · torch ${s.torch} · ultralytics ${s.ultralytics}',
        child: Pill(
          s.gpu ? s.deviceLabel : 'CPU',
          icon: s.gpu ? Icons.bolt : Icons.memory,
          color: AppColors.primary,
          background: AppColors.primaryTint,
        ),
      ),
    );
  }
}

Future<void> _guard(BuildContext context, Future<void> Function() fn) async {
  try {
    await fn();
  } on ApiException catch (e) {
    if (context.mounted) showError(context, e);
  }
}

class _Actions extends ConsumerWidget {
  const _Actions(this.run);
  final Run run;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final notifier = ref.read(runProvider(run.id).notifier);
    final failed = const {'error', 'cancelled', 'interrupted'}.contains(run.status);
    return Wrap(spacing: 8, runSpacing: 8, children: [
      if (run.active)
        OutlinedButton.icon(
          onPressed: () => _guard(context, notifier.cancel),
          icon: const Icon(Icons.stop_circle_outlined, size: 18),
          label: const Text('Cancel'),
        )
      else if (run.status == 'ready')
        FilledButton.icon(
          onPressed: () => _guard(context, notifier.rerun),
          icon: const Icon(Icons.play_arrow_rounded, size: 20),
          label: const Text('Analyze'),
        )
      else if (failed)
        FilledButton.icon(
          onPressed: () => _guard(context, notifier.rerun),
          icon: const Icon(Icons.replay, size: 18),
          label: const Text('Retry'),
        )
      else
        Tooltip(
          message: 'Process again. Steps whose inputs did not change are reused from the cache.',
          child: OutlinedButton.icon(
            onPressed: () => _guard(context, notifier.rerun),
            icon: const Icon(Icons.replay, size: 18),
            label: const Text('Rerun'),
          ),
        ),
      OutlinedButton.icon(
        style: OutlinedButton.styleFrom(foregroundColor: AppColors.error),
        onPressed: () async {
          if (await deleteRunFlow(context, ref, run) && context.mounted) context.go('/');
        },
        icon: const Icon(Icons.delete_outline, size: 18),
        label: const Text('Delete'),
      ),
    ]);
  }
}

class _AnalyzeCallout extends ConsumerWidget {
  const _AnalyzeCallout(this.run);
  final Run run;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = Theme.of(context).textTheme;
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: AppColors.primaryTint,
        borderRadius: BorderRadius.circular(kRadius),
        border: Border.all(color: AppColors.primary.withValues(alpha: 0.25)),
      ),
      child: Row(children: [
        const Icon(Icons.check_circle_outline, color: AppColors.primary, size: 28),
        const SizedBox(width: 16),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Inputs ready, not processed yet', style: t.titleMedium?.copyWith(color: AppColors.primary)),
            const SizedBox(height: 2),
            Text('Analyze runs the LiDAR pipeline, YOLO11m on every video frame, the time alignment and the fusion. '
                'It keeps running if you close this page.', style: t.bodyMedium),
          ]),
        ),
        const SizedBox(width: 16),
        FilledButton.icon(
          style: FilledButton.styleFrom(padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 18)),
          onPressed: () => _guard(context, ref.read(runProvider(run.id).notifier).rerun),
          icon: const Icon(Icons.play_arrow_rounded, size: 22),
          label: const Text('Analyze'),
        ),
      ]),
    );
  }
}

class _ProgressCard extends ConsumerWidget {
  const _ProgressCard(this.run);
  final Run run;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final job = run.job!;
    final failed = run.status == 'error' || job.state == 'error';
    final interrupted = run.status == 'interrupted' || run.status == 'cancelled';
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        CardTitle(
          run.active ? 'Processing' : 'Progress',
          icon: Icons.timeline,
          subtitle: run.active
              ? 'Runs on the backend: you can close or refresh this page and come back.'
              : null,
        ),
        const SizedBox(height: 18),
        JobProgress(job),
        if (failed && run.error != null) ...[
          const SizedBox(height: 18),
          Notice(
            run.error!,
            kind: NoticeKind.error,
            title: job.failedStep != null ? '${job.failedStep} failed' : 'The run failed',
            action: FilledButton.icon(
              onPressed: () => _guard(context, ref.read(runProvider(run.id).notifier).rerun),
              icon: const Icon(Icons.replay, size: 18),
              label: const Text('Retry'),
            ),
          ),
        ],
        if (interrupted && run.error != null) ...[
          const SizedBox(height: 18),
          Notice(
            run.error!,
            kind: NoticeKind.warning,
            action: TextButton(
              onPressed: () => _guard(context, ref.read(runProvider(run.id).notifier).rerun),
              child: const Text('Retry'),
            ),
          ),
        ],
      ]),
    );
  }
}

class _ViewsCard extends ConsumerWidget {
  const _ViewsCard(this.run);
  final Run run;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final screen = (run.results?['media'] as Map?)?['lidar_screen'];
    final api = ref.read(apiProvider);
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        CardTitle('Views', icon: Icons.dashboard_outlined,
            subtitle: run.validated
                ? 'Live view: choose LiDAR only, Camera only or Fusion, run it and replay the detections.'
                : 'Available once the inputs are validated.'),
        const SizedBox(height: 16),
        Wrap(spacing: 10, runSpacing: 10, children: [
          FilledButton.icon(
            onPressed: run.validated ? () => context.go('/runs/${run.id}/live') : null,
            icon: const Icon(Icons.sensors),
            label: const Text('Live view'),
          ),
          Tooltip(
            message: 'Phase 4',
            child: OutlinedButton.icon(onPressed: null, icon: const Icon(Icons.insights), label: const Text('Results')),
          ),
          if (screen != null)
            OutlinedButton.icon(
              onPressed: () => launchUrl(Uri.parse(api.mediaUrl(run.id, roleLidarScreen)), webOnlyWindowName: '_blank'),
              icon: const Icon(Icons.ondemand_video_outlined, size: 18),
              label: Text(screen['path'] == 'cache' ? 'Sensor UI recording (H.264)' : 'Sensor UI recording'),
            ),
        ]),
      ]),
    );
  }
}
