import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/models.dart';
import '../../state/new_run.dart';
import '../../state/providers.dart';
import '../../theme.dart';
import '../../util/format.dart';
import '../../widgets/common.dart';
import '../../widgets/inputs_report.dart';
import 'gt_editor.dart';
import 'source_card.dart';

class NewRunScreen extends ConsumerWidget {
  const NewRunScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final st = ref.watch(newRunProvider);
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
        Text('New run', style: t.headlineSmall),
        const SizedBox(height: 4),
        Text('Choose the recording, optionally add the ground truth, then analyze.',
            style: t.bodyMedium?.copyWith(color: AppColors.textSecondary)),
        const SizedBox(height: 24),
        if (st.runId != null) _ProgressView(runId: st.runId!) else const _Form(),
      ]),
    );
  }
}

class _Form extends StatelessWidget {
  const _Form();

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, c) {
      if (c.maxWidth >= 940) {
        return const Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(flex: 11, child: SourceCard()),
          SizedBox(width: 20),
          Expanded(
            flex: 9,
            child: Column(children: [GroundTruthCard(), SizedBox(height: 20), _AnalyzeCard()]),
          ),
        ]);
      }
      return const Column(children: [
        SourceCard(),
        SizedBox(height: 20),
        GroundTruthCard(),
        SizedBox(height: 20),
        _AnalyzeCard(),
      ]);
    });
  }
}

class _AnalyzeCard extends ConsumerWidget {
  const _AnalyzeCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final st = ref.watch(newRunProvider);
    final signedIn = ref.watch(driveProvider).value?.signedIn ?? false;
    final problems = st.problems(driveSignedIn: signedIn);
    final t = Theme.of(context).textTheme;
    final drive = st.source == SourceKind.drive;

    final files = drive
        ? [for (final r in allRoles) if (st.selectedDriveFile(r) != null) st.selectedDriveFile(r)!.name]
        : [for (final r in allRoles) if (st.uploads[r] != null) st.uploads[r]!.name];
    final bytes = drive ? st.downloadBytes : st.uploadBytes;

    Widget line(IconData icon, String label, String value) => Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Icon(icon, size: 17, color: AppColors.textSecondary),
            const SizedBox(width: 10),
            SizedBox(width: 92, child: Text(label, style: t.bodySmall)),
            Expanded(child: Text(value, style: t.bodyMedium)),
          ]),
        );

    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        const CardTitle('Analyze', icon: Icons.play_circle_outline),
        const SizedBox(height: 14),
        line(drive ? Icons.add_to_drive : Icons.upload_file, 'Source',
            drive ? (st.listing?.folderPath ?? 'Google Drive') : 'Upload from this computer'),
        line(Icons.insert_drive_file_outlined, 'Files',
            files.isEmpty ? '—' : '${files.join(', ')}  (${formatBytes(bytes)})'),
        line(Icons.flag_outlined, 'Ground truth',
            st.gtEnabled ? '${st.segments.length} segment(s)${st.gtPreset != null ? ' · ${st.gtPreset}' : ''}' : 'None'),
        const SizedBox(height: 6),
        if (st.submitError != null) ...[
          Notice(st.submitError!, kind: NoticeKind.error),
          const SizedBox(height: 12),
        ],
        if (problems.isNotEmpty) ...[
          for (final p in problems)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Row(children: [
                const Icon(Icons.radio_button_unchecked, size: 14, color: AppColors.textSecondary),
                const SizedBox(width: 8),
                Expanded(child: Text(p, style: t.bodySmall)),
              ]),
            ),
          const SizedBox(height: 10),
        ],
        FilledButton.icon(
          onPressed: problems.isEmpty && !st.submitting ? () => ref.read(newRunProvider.notifier).analyze() : null,
          icon: st.submitting
              ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
              : const Icon(Icons.play_arrow_rounded),
          label: Text(drive ? 'Analyze' : 'Upload and analyze'),
        ),
        const SizedBox(height: 8),
        Text(
          drive
              ? 'Downloads the selected files into data/runs/ on this laptop, then checks them.'
              : 'Uploads the files into data/runs/ on this laptop, then checks them.',
          style: t.bodySmall,
          textAlign: TextAlign.center,
        ),
      ]),
    );
  }
}

/// Shown after "Analyze": live progress of the run's job, then the result.
class _ProgressView extends ConsumerWidget {
  const _ProgressView({required this.runId});
  final String runId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final st = ref.watch(newRunProvider);
    final ctl = ref.read(newRunProvider.notifier);
    final runAsync = ref.watch(runProvider(runId));
    final t = Theme.of(context).textTheme;

    return runAsync.when(
      skipLoadingOnRefresh: true,
      loading: () => const AppCard(child: Center(child: Padding(padding: EdgeInsets.all(24), child: CircularProgressIndicator()))),
      error: (e, _) => AppCard(child: Notice(e.toString(), kind: NoticeKind.error)),
      data: (run) {
        final job = run.job;
        final finished = !run.active && !st.submitting;
        return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          AppCard(
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              CardTitle(
                run.name,
                icon: Icons.timeline,
                subtitle: run.isDrive ? 'From Google Drive · ${run.source['path'] ?? ''}' : 'Uploaded files',
                trailing: StatusPill(run),
              ),
              const SizedBox(height: 20),
              if (job != null) JobProgress(job),
              if (st.submitError != null) ...[
                const SizedBox(height: 16),
                Notice(st.submitError!, kind: NoticeKind.error),
              ],
              if (run.status == 'error' && run.error != null && st.submitError == null) ...[
                const SizedBox(height: 16),
                Notice(run.error!, kind: NoticeKind.error,
                    title: job?.failedStep != null ? '${job!.failedStep} failed' : 'The run failed'),
              ],
              if (run.active && !st.submitting) ...[
                const SizedBox(height: 16),
                const Notice(
                  'The job runs on the backend: you can leave this page, close the tab or refresh. '
                  'The run page shows the current progress when you come back.',
                ),
              ],
              if (run.status == 'processed') ...[
                const SizedBox(height: 16),
                const Notice('LiDAR, YOLO, time alignment and fusion are done. Open the run to see the results.',
                    title: 'Processed'),
              ],
              const SizedBox(height: 20),
              Wrap(spacing: 10, runSpacing: 10, alignment: WrapAlignment.end, children: [
                if (!finished)
                  OutlinedButton(onPressed: ctl.cancelRun, child: const Text('Cancel')),
                if (finished && run.status != 'processed')
                  OutlinedButton(onPressed: ctl.backToForm, child: const Text('Back to the form')),
                if (finished)
                  OutlinedButton(
                    onPressed: () {
                      ctl.startOver();
                      ref.invalidate(runsProvider);
                    },
                    child: const Text('New run'),
                  ),
                if (!st.submitting)
                  FilledButton(
                    onPressed: () {
                      ctl.startOver();
                      context.go(finished ? '/runs/${run.id}' : '/');
                    },
                    child: Text(finished ? 'Open run' : 'Continue in the background'),
                  ),
              ]),
              if (st.submitting && !run.isDrive)
                Padding(
                  padding: const EdgeInsets.only(top: 10),
                  child: Text('Keep this tab open until the upload has finished.',
                      style: t.bodySmall, textAlign: TextAlign.end),
                ),
            ]),
          ),
          if (run.validation != null) ...[
            const SizedBox(height: 20),
            AppCard(
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                const CardTitle('Inputs', icon: Icons.fact_check_outlined),
                const SizedBox(height: 16),
                InputsReport(run),
              ]),
            ),
          ],
        ]);
      },
    );
  }
}
