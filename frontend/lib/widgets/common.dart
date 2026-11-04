import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/models.dart';
import '../config.dart';
import '../state/providers.dart';
import '../theme.dart';
import '../util/format.dart';

/// Page frame: top bar (title, subtitle, backend status) + centred content.
class AppShell extends ConsumerWidget {
  const AppShell({super.key, required this.child, this.maxWidth = 1120, this.endDrawer, this.scaffoldKey});
  final Widget child;
  final double maxWidth;
  final Widget? endDrawer;
  final GlobalKey<ScaffoldState>? scaffoldKey;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final health = ref.watch(backendHealthProvider);
    return Scaffold(
      key: scaffoldKey,
      endDrawer: endDrawer,
      body: Column(
        children: [
          Container(
            height: 64,
            padding: const EdgeInsets.symmetric(horizontal: 24),
            decoration: const BoxDecoration(
              color: Colors.white,
              border: Border(bottom: BorderSide(color: AppColors.border)),
            ),
            child: Row(
              children: [
                const _Logo(),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(appTitle,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
                      Text(appSubtitle, style: Theme.of(context).textTheme.bodySmall),
                    ],
                  ),
                ),
                ConnectionBadge(connected: health),
              ],
            ),
          ),
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(24, 28, 24, 48),
              child: Center(
                child: ConstrainedBox(constraints: BoxConstraints(maxWidth: maxWidth), child: child),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _Logo extends StatelessWidget {
  const _Logo();
  @override
  Widget build(BuildContext context) {
    return Container(
      width: 36,
      height: 36,
      decoration: BoxDecoration(color: AppColors.primary, borderRadius: BorderRadius.circular(9)),
      child: const Icon(Icons.groups_2_outlined, color: Colors.white, size: 21),
    );
  }
}

class ConnectionBadge extends StatelessWidget {
  const ConnectionBadge({super.key, required this.connected});
  final bool? connected;

  @override
  Widget build(BuildContext context) {
    final (color, label) = switch (connected) {
      true => (AppColors.lidar, 'Backend connected'),
      false => (AppColors.error, 'Backend offline'),
      null => (AppColors.textSecondary, 'Connecting…'),
    };
    return Tooltip(
      message: backendUrl,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(
          color: Colors.white,
          border: Border.all(color: AppColors.border),
          borderRadius: BorderRadius.circular(999),
        ),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Container(width: 8, height: 8, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
          const SizedBox(width: 8),
          Text(label, style: const TextStyle(fontSize: 12.5, color: AppColors.textSecondary, fontWeight: FontWeight.w500)),
        ]),
      ),
    );
  }
}

/// White card, thin border, soft shadow, 12 px radius.
class AppCard extends StatelessWidget {
  const AppCard({super.key, required this.child, this.padding = const EdgeInsets.all(20)});
  final Widget child;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    // The white background is a Material (not a coloured DecoratedBox) so that
    // list tiles and ink splashes inside the card paint correctly.
    return DecoratedBox(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(kRadius),
        boxShadow: const [
          BoxShadow(color: Color(0x0A101828), blurRadius: 3, offset: Offset(0, 1)),
          BoxShadow(color: Color(0x08101828), blurRadius: 12, offset: Offset(0, 4)),
        ],
      ),
      child: Material(
        color: AppColors.card,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(kRadius),
          side: const BorderSide(color: AppColors.border),
        ),
        clipBehavior: Clip.antiAlias,
        child: Padding(padding: padding, child: child),
      ),
    );
  }
}

class CardTitle extends StatelessWidget {
  const CardTitle(this.title, {super.key, this.subtitle, this.trailing, this.icon});
  final String title;
  final String? subtitle;
  final Widget? trailing;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (icon != null) ...[
        Padding(padding: const EdgeInsets.only(top: 1), child: Icon(icon, size: 20, color: AppColors.primary)),
        const SizedBox(width: 10),
      ],
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: t.titleMedium),
          if (subtitle != null) ...[const SizedBox(height: 2), Text(subtitle!, style: t.bodySmall)],
        ]),
      ),
      ?trailing,
    ]);
  }
}

enum NoticeKind { info, warning, error }

/// Inline message box. Red is used for errors only.
class Notice extends StatelessWidget {
  const Notice(this.message, {super.key, this.kind = NoticeKind.info, this.action, this.title});
  final String message;
  final String? title;
  final NoticeKind kind;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final (bg, fg, icon) = switch (kind) {
      NoticeKind.error => (AppColors.errorTint, AppColors.error, Icons.error_outline),
      NoticeKind.warning => (AppColors.neutralTint, AppColors.text, Icons.info_outline),
      NoticeKind.info => (AppColors.primaryTint, AppColors.primary, Icons.info_outline),
    };
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
      decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(8)),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(icon, size: 18, color: fg),
        const SizedBox(width: 10),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (title != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 2),
                child: Text(title!, style: TextStyle(color: fg, fontWeight: FontWeight.w600, fontSize: 13.5)),
              ),
            SelectableText(message,
                style: TextStyle(color: kind == NoticeKind.error ? fg : AppColors.text, fontSize: 13.5, height: 1.4)),
          ]),
        ),
        if (action != null) ...[const SizedBox(width: 8), action!],
      ]),
    );
  }
}

/// Small rounded label.
class Pill extends StatelessWidget {
  const Pill(this.label, {super.key, this.color = AppColors.textSecondary, this.background = AppColors.neutralTint, this.icon});
  final String label;
  final Color color;
  final Color background;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3),
      decoration: BoxDecoration(color: background, borderRadius: BorderRadius.circular(999)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        if (icon != null) ...[Icon(icon, size: 13, color: color), const SizedBox(width: 4)],
        Text(label, style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w600)),
      ]),
    );
  }
}

/// Colour-coded run status.
class StatusPill extends StatelessWidget {
  const StatusPill(this.run, {super.key});
  final Run run;

  @override
  Widget build(BuildContext context) {
    final step = run.job?.currentStep;
    final pct = step?.progress == null ? '' : ' ${(step!.progress! * 100).round()}%';
    final overall = run.job?.progress == null ? '' : ' ${(run.job!.progress! * 100).round()}%';
    return switch (run.status) {
      'uploading' => Pill('Uploading$pct', color: AppColors.primary, background: AppColors.primaryTint, icon: Icons.upload),
      'downloading' => Pill('Downloading$pct', color: AppColors.primary, background: AppColors.primaryTint, icon: Icons.download),
      'queued' => const Pill('Queued', color: AppColors.primary, background: AppColors.primaryTint, icon: Icons.schedule),
      'validating' => const Pill('Checking inputs', color: AppColors.primary, background: AppColors.primaryTint, icon: Icons.fact_check_outlined),
      'processing' => Pill('Processing$overall', color: AppColors.primary, background: AppColors.primaryTint, icon: Icons.memory),
      'ready' => const Pill('Inputs ready', color: AppColors.primary, background: AppColors.neutralTint, icon: Icons.check_circle_outline),
      'processed' => const Pill('Processed', color: AppColors.primary, background: AppColors.neutralTint, icon: Icons.check_circle),
      'error' => const Pill('Error', color: AppColors.error, background: AppColors.errorTint, icon: Icons.error_outline),
      'interrupted' => const Pill('Interrupted', icon: Icons.pause_circle_outline),
      'cancelled' => const Pill('Cancelled', icon: Icons.block),
      _ => Pill(run.status),
    };
  }
}

/// Overall progress of a job + its steps (waiting / running / done / failed).
class JobProgress extends StatelessWidget {
  const JobProgress(this.job, {super.key, this.showOverall = true});
  final Job job;
  final bool showOverall;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final steps = job.steps;
    final running = job.active;
    final pct = ((job.progress ?? 0) * 100).round();
    final overall = <String>[
      '$pct%',
      if (job.elapsedS != null) '${formatClock(job.elapsedS)} elapsed',
      if (running && job.etaS != null) formatEtaShort(job.etaS),
    ];
    final failed = job.state == 'error' || job.state == 'interrupted';
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      if (showOverall) ...[
        Row(children: [
          Text(
            switch (job.state) {
              'done' => 'Completed',
              'error' => 'Failed',
              'cancelled' => 'Cancelled',
              'interrupted' => 'Interrupted',
              'queued' => 'Queued (waiting for another run to finish)',
              _ => 'Overall progress',
            },
            style: t.titleSmall?.copyWith(color: failed ? AppColors.error : AppColors.text),
          ),
          const Spacer(),
          Text(overall.join('  ·  '), style: t.bodySmall?.copyWith(fontFeatures: const [FontFeature.tabularFigures()])),
        ]),
        const SizedBox(height: 8),
        ClipRRect(
          borderRadius: BorderRadius.circular(99),
          child: LinearProgressIndicator(
            value: job.progress ?? 0,
            minHeight: 10,
            color: failed ? AppColors.error : AppColors.primary,
          ),
        ),
        const SizedBox(height: 20),
      ],
      for (var i = 0; i < steps.length; i++) ...[
        if (i > 0) const SizedBox(height: 14),
        _StepRow(steps[i], index: i + 1),
      ],
    ]);
  }
}

class _StepRow extends StatelessWidget {
  const _StepRow(this.step, {required this.index});
  final JobStep step;
  final int index;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final running = step.state == 'running';
    final icon = switch (step.state) {
      'done' => const Icon(Icons.check_circle, size: 20, color: AppColors.primary),
      'running' => const SizedBox(
          width: 20,
          height: 20,
          child: Padding(
            padding: EdgeInsets.all(1.5),
            child: CircularProgressIndicator(strokeWidth: 2.6, backgroundColor: AppColors.primaryTint),
          )),
      'error' => const Icon(Icons.error, size: 20, color: AppColors.error),
      'skipped' => const Icon(Icons.remove_circle_outline, size: 20, color: AppColors.textSecondary),
      'cancelled' => const Icon(Icons.block, size: 20, color: AppColors.textSecondary),
      _ => Container(
          width: 20,
          height: 20,
          alignment: Alignment.center,
          decoration: BoxDecoration(shape: BoxShape.circle, border: Border.all(color: AppColors.border, width: 1.5)),
          child: Text('$index', style: const TextStyle(fontSize: 11, color: AppColors.textSecondary)),
        ),
    };

    // Running: "frame 120 / 454 · 26% · 0:42 elapsed · ETA 2 min"
    final details = <String>[];
    if (running) {
      if (step.total != null && step.done != null) {
        details.add(switch (step.unit) {
          'frames' => 'frame ${step.done!.round()} / ${step.total!.round()}',
          'bytes' => '${formatBytes(step.done)} / ${formatBytes(step.total)}',
          'files' => '${step.done!.round()} / ${step.total!.round()} files',
          _ => '${step.done!.round()} / ${step.total!.round()}',
        });
      }
      if (step.progress != null) details.add('${(step.progress! * 100).round()}%');
      if (step.elapsedS != null) details.add('${formatClock(step.elapsedS)} elapsed');
      if (step.etaS != null) details.add(formatEtaShort(step.etaS));
    }
    final right = switch (step.state) {
      'running' => '',
      'pending' => 'waiting',
      'done' || 'skipped' || 'error' => step.elapsedS == null ? '' : formatSeconds(step.elapsedS, digits: 1),
      _ => '',
    };
    const tabular = [FontFeature.tabularFigures()];

    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Padding(padding: const EdgeInsets.only(top: 1), child: icon),
      const SizedBox(width: 12),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
              child: Text(step.label,
                  style: t.titleSmall?.copyWith(
                      color: switch (step.state) {
                        'pending' => AppColors.textSecondary,
                        'error' => AppColors.error,
                        _ => AppColors.text,
                      })),
            ),
            if (right.isNotEmpty) Text(right, style: t.bodySmall?.copyWith(fontFeatures: tabular)),
          ]),
          if (details.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 3),
              child: Text(details.join('  ·  '),
                  style: t.bodySmall?.copyWith(
                      color: AppColors.text, fontWeight: FontWeight.w500, fontFeatures: tabular)),
            ),
          if (step.message.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text(step.message,
                  style: t.bodySmall?.copyWith(color: step.state == 'error' ? AppColors.error : AppColors.textSecondary)),
            ),
          if (running)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(99),
                child: LinearProgressIndicator(value: step.progress, minHeight: 6),
              ),
            ),
        ]),
      ),
    ]);
  }
}

Future<bool> confirmDialog(
  BuildContext context, {
  required String title,
  required String message,
  required String confirmLabel,
  bool destructive = false,
}) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(title, style: Theme.of(ctx).textTheme.titleLarge),
      content: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 420), child: Text(message)),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
        FilledButton(
          style: destructive ? FilledButton.styleFrom(backgroundColor: AppColors.error) : null,
          onPressed: () => Navigator.pop(ctx, true),
          child: Text(confirmLabel),
        ),
      ],
    ),
  );
  return ok ?? false;
}

void showError(BuildContext context, Object e) {
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(
    backgroundColor: AppColors.error,
    content: Text(e.toString()),
  ));
}
