import 'package:flutter/scheduler.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:material_ui/material_ui.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/models.dart';
import '../state/providers.dart';
import '../theme.dart';
import '../util/format.dart';
import '../widgets/common.dart';
import 'camera_view.dart';
import 'hud.dart';
import 'lidar_view.dart';
import 'live_controller.dart';
import 'live_models.dart';
import 'params_drawer.dart';
import 'playback.dart';
import 'player_bar.dart';
import 'results_panel.dart';

/// Live view: choose a mode → Run → replay with detections.
/// The view follows the mode: LiDAR only → bird's-eye view, Camera only →
/// camera view, Fusion → both side by side with the fused count above.
class LiveScreen extends ConsumerStatefulWidget {
  const LiveScreen({super.key, required this.runId, this.initialMode, this.initialTime, this.openParams = false});
  final String runId;
  final LiveMode? initialMode;
  final double? initialTime;
  final bool openParams; // deep link ?panel=params

  @override
  ConsumerState<LiveScreen> createState() => _LiveScreenState();
}

class _LiveScreenState extends ConsumerState<LiveScreen> with SingleTickerProviderStateMixin {
  final _scaffold = GlobalKey<ScaffoldState>();
  PlaybackController? _pb;
  late final Ticker _ticker;
  bool _openedParams = false;

  @override
  void initState() {
    super.initState();
    ref.read(liveProvider(widget.runId).notifier).setInitialMode(widget.initialMode);
    _ticker = createTicker((e) => _pb?.tick(e))..start();
    HardwareKeyboard.instance.addHandler(_onKey);
  }

  @override
  void dispose() {
    HardwareKeyboard.instance.removeHandler(_onKey);
    _ticker.dispose();
    _pb?.dispose();
    super.dispose();
  }

  /// Space: play/pause · ←/→: previous/next frame · Shift + ←/→: ∓1 s.
  bool _onKey(KeyEvent e) {
    final pb = _pb;
    if (pb == null || e is KeyUpEvent) return false;
    final focused = FocusManager.instance.primaryFocus?.context?.widget;
    if (focused is EditableText) return false; // typing in a parameter field
    final shift = HardwareKeyboard.instance.isShiftPressed;
    if (e.logicalKey == LogicalKeyboardKey.space && e is KeyDownEvent) {
      pb.toggle();
      return true;
    }
    if (e.logicalKey == LogicalKeyboardKey.arrowLeft) {
      shift ? pb.jump(-1) : pb.step(-1);
      return true;
    }
    if (e.logicalKey == LogicalKeyboardKey.arrowRight) {
      shift ? pb.jump(1) : pb.step(1);
      return true;
    }
    return false;
  }

  PlaybackController _playback(LiveState st) {
    final cam = (st.run?.validation?['camera_video'] as Json?)?['info'] as Json?;
    final fps = (cam?['fps'] as num?)?.toDouble() ?? 10;
    final frames = (cam?['frames'] as num?)?.toDouble() ?? 0;
    final pb = _pb ??= PlaybackController(duration: frames / fps, fps: fps)..seek(widget.initialTime ?? 0);
    return pb;
  }

  LiveCounts _countsAt(LiveState st, double t) {
    final r = st.result;
    if (r == null) return LiveCounts(t: t);
    final n = r.t.length;
    final i = gridIndex(t, r.gridHz, n);
    final gt = r.series('gt')?[i];
    int? yolo;
    if (st.mode != LiveMode.lidar && st.yolo != null) {
      yolo = st.yolo!.boxesAt((t * r.fps + 1e-6).floor(), st.conf).length;
    }
    int? lidar;
    var available = true;
    final ld = st.lidarFor(r);
    if (st.mode != LiveMode.camera && ld != null) {
      final j = ld.frameAt(t + r.lagS);
      available = j != null;
      lidar = j == null ? null : ld.frames[j].smooth;
    }
    final fusedSeries = st.mode == LiveMode.fusion ? r.series('fused') : null;
    final fused = fusedSeries?[i];
    return LiveCounts(t: t, gt: gt, lidar: lidar, yolo: yolo, fused: fused, lidarAvailable: available);
  }

  @override
  Widget build(BuildContext context) {
    final st = ref.watch(liveProvider(widget.runId));
    final t = Theme.of(context).textTheme;

    Widget back() => Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: () => context.go('/runs/${widget.runId}'),
            icon: const Icon(Icons.arrow_back, size: 18),
            label: const Text('Run page'),
          ),
        );

    if (st.loading) {
      return const AppShell(child: Padding(padding: EdgeInsets.all(64), child: Center(child: CircularProgressIndicator())));
    }
    if (st.error != null) {
      return AppShell(child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        back(),
        const SizedBox(height: 12),
        AppCard(child: Notice(st.error!, kind: NoticeKind.error, title: 'The Live view is not available')),
      ]));
    }

    final pb = _playback(st);
    if (widget.openParams && !_openedParams) {
      _openedParams = true;
      Future.delayed(const Duration(milliseconds: 400), () {
        if (mounted) _scaffold.currentState?.openEndDrawer();
      });
    }
    final r = st.result;
    final ld = st.lidarFor(r);
    pb.stepTimes = st.mode == LiveMode.lidar && ld != null && r != null
        ? [for (final f in ld.frames) f.t - r.lagS]
        : null;
    LiveCounts countsAt(double time) => _countsAt(st, time);
    final screen = (st.run?.results?['media'] as Json?)?['lidar_screen'];

    return AppShell(
      scaffoldKey: _scaffold,
      maxWidth: 1480,
      endDrawer: ParamsDrawer(runId: widget.runId),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        back(),
        Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
          Text('Live view', style: t.headlineSmall),
          const SizedBox(width: 12),
          Flexible(child: Text(st.run?.name ?? '', style: t.titleLarge?.copyWith(color: AppColors.textSecondary),
              overflow: TextOverflow.ellipsis)),
          const SizedBox(width: 12),
          const Pill('Recorded', icon: Icons.fiber_manual_record, color: AppColors.primary, background: AppColors.primaryTint),
          const SizedBox(width: 8),
          const Tooltip(
            message: 'A live Qb2 + camera stream is planned (LiveSource); this view replays a recorded run.',
            child: Pill('Live sensor (not connected)', icon: Icons.sensors_off),
          ),
          const Spacer(),
          if (screen != null)
            TextButton.icon(
              onPressed: () => launchUrl(Uri.parse(ref.read(apiProvider).mediaUrl(widget.runId, roleLidarScreen)),
                  webOnlyWindowName: '_blank'),
              icon: const Icon(Icons.open_in_new, size: 16),
              label: const Text('Sensor UI recording'),
            ),
        ]),
        const SizedBox(height: 16),
        _ModeBar(runId: widget.runId, st: st, onParams: () => _scaffold.currentState?.openEndDrawer()),
        if (st.actionError != null) ...[
          const SizedBox(height: 12),
          Notice(st.actionError!, kind: NoticeKind.error),
        ],
        if (st.isStale(st.mode)) ...[
          const SizedBox(height: 12),
          _StaleBanner(runId: widget.runId, st: st),
        ],
        const SizedBox(height: 16),
        _Views(runId: widget.runId, st: st, playback: pb, countsAt: countsAt),
        if (r != null) ...[
          const SizedBox(height: 12),
          PlayerBar(playback: pb),
          const SizedBox(height: 6),
          Text('Space: play/pause · ←/→: one frame · Shift + ←/→: one second', style: t.bodySmall),
          const SizedBox(height: 20),
          ResultsPanel(runId: widget.runId, playback: pb, countsAt: countsAt),
        ],
      ]),
    );
  }
}

class _ModeBar extends ConsumerWidget {
  const _ModeBar({required this.runId, required this.st, required this.onParams});
  final String runId;
  final LiveState st;
  final VoidCallback onParams;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ctl = ref.read(liveProvider(runId).notifier);
    final job = st.liveJob;
    final running = job != null && job.active && job.kind.startsWith('mode:');
    final upToDate = st.cached(st.mode);
    return AppCard(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
      child: Wrap(spacing: 16, runSpacing: 12, crossAxisAlignment: WrapCrossAlignment.center, children: [
        // fixed width: the segments share it equally, so no label is clipped
        SizedBox(
          width: 480,
          child:
          SegmentedButton<LiveMode>(
            showSelectedIcon: false,
            style: SegmentedButton.styleFrom(
              selectedBackgroundColor: AppColors.primaryTint,
              selectedForegroundColor: AppColors.primary,
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
            ),
            segments: [
              for (final m in LiveMode.values)
                ButtonSegment(
                  value: m,
                  enabled: st.available(m) && !running,
                  tooltip: st.available(m) ? m.label : st.unavailableReason(m),
                  icon: Icon(switch (m) {
                    LiveMode.lidar => Icons.radar,
                    LiveMode.camera => Icons.videocam_outlined,
                    LiveMode.fusion => Icons.merge_type,
                  }, color: st.available(m) ? modeColors[m] : null),
                  label: Text(switch (m) {
                    LiveMode.lidar => 'LiDAR only',
                    LiveMode.camera => 'Camera only',
                    LiveMode.fusion => 'Fusion',
                  }, maxLines: 1, softWrap: false),
                ),
            ],
            selected: {st.mode},
            onSelectionChanged: (s) => ctl.setMode(s.first),
          ),
        ),
        if (running)
          SizedBox(width: 420, child: _RunProgress(job: job, onCancel: ctl.cancel))
        else if (upToDate)
          OutlinedButton.icon(
            onPressed: null,
            icon: const Icon(Icons.check_circle_outline, size: 18),
            label: const Text('Up to date'),
          )
        else
          FilledButton.icon(
            onPressed: st.available(st.mode) && !st.busy && !st.resolving ? ctl.run : null,
            icon: const Icon(Icons.play_arrow_rounded),
            label: Text('Run ${st.mode.short}'),
          ),
        Badge(
          isLabelVisible: st.nonBest > 0,
          backgroundColor: amber,
          label: Text('${st.nonBest}'),
          child: OutlinedButton.icon(
            onPressed: onParams,
            icon: const Icon(Icons.tune, size: 18),
            label: const Text('Parameters'),
          ),
        ),
        if (st.mode != LiveMode.lidar && st.calibration != null)
          FilterChip(
            selected: st.showRoi,
            onSelected: (_) => ctl.toggleRoi(),
            avatar: const Icon(Icons.crop_free, size: 16),
            label: const Text('ROI (approximate calibration)'),
          ),
        if (st.dataLoading)
          const Row(mainAxisSize: MainAxisSize.min, children: [
            SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2)),
            SizedBox(width: 8),
            Text('Loading results…', style: TextStyle(fontSize: 12.5, color: AppColors.textSecondary)),
          ]),
      ]),
    );
  }
}

class _RunProgress extends StatelessWidget {
  const _RunProgress({required this.job, required this.onCancel});
  final Job job;
  final VoidCallback onCancel;

  @override
  Widget build(BuildContext context) {
    final s = job.currentStep;
    final parts = <String>[
      s?.label ?? (job.state == 'queued' ? 'Queued' : 'Starting'),
      if (s != null && s.unit == 'frames' && s.total != null) 'frame ${s.done?.round()} / ${s.total?.round()}',
      '${((job.progress ?? 0) * 100).round()}%',
      if (job.etaS != null) formatEtaShort(job.etaS),
    ];
    return Row(children: [
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          Text(parts.join(' · '), style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600,
              fontFeatures: [FontFeature.tabularFigures()])),
          const SizedBox(height: 6),
          ClipRRect(
            borderRadius: BorderRadius.circular(99),
            child: LinearProgressIndicator(value: job.progress ?? 0, minHeight: 6),
          ),
        ]),
      ),
      const SizedBox(width: 8),
      TextButton(onPressed: onCancel, child: const Text('Cancel')),
    ]);
  }
}

class _StaleBanner extends ConsumerWidget {
  const _StaleBanner({required this.runId, required this.st});
  final String runId;
  final LiveState st;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 10, 10, 10),
      decoration: BoxDecoration(color: amberBg, borderRadius: BorderRadius.circular(8),
          border: Border.all(color: amberBorder)),
      child: Row(children: [
        const Icon(Icons.info_outline, color: amber, size: 18),
        const SizedBox(width: 10),
        const Expanded(
          child: Text('Parameters changed, run again. The views show the results of the previous run.',
              style: TextStyle(color: amber, fontWeight: FontWeight.w600)),
        ),
        FilledButton(
          onPressed: st.busy ? null : ref.read(liveProvider(runId).notifier).run,
          child: Text('Run ${st.mode.short}'),
        ),
      ]),
    );
  }
}

class _Views extends ConsumerWidget {
  const _Views({required this.runId, required this.st, required this.playback, required this.countsAt});
  final String runId;
  final LiveState st;
  final PlaybackController playback;
  final CountsAt countsAt;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final r = st.result;
    final t = Theme.of(context).textTheme;
    if (r == null) {
      return AppCard(
        padding: const EdgeInsets.symmetric(vertical: 56, horizontal: 24),
        child: Column(children: [
          Icon(switch (st.mode) {
            LiveMode.lidar => Icons.radar,
            LiveMode.camera => Icons.videocam_outlined,
            LiveMode.fusion => Icons.merge_type,
          }, size: 40, color: modeColors[st.mode]),
          const SizedBox(height: 12),
          Text('${st.mode.label} has not been run with these parameters yet.', style: t.titleMedium),
          const SizedBox(height: 4),
          Text(switch (st.mode) {
            LiveMode.lidar => 'Run computes the LiDAR pipeline only (~10 s).',
            LiveMode.camera => 'Run computes YOLO11m on every video frame (a few minutes on CPU, once per video).',
            LiveMode.fusion => 'Run reuses the LiDAR and YOLO results, then aligns them and fits Stack-GBT.',
          }, style: t.bodySmall),
        ]),
      );
    }
    final api = ref.read(apiProvider);
    final yolo = st.yolo;
    final ld = st.lidarFor(r);
    final roi = (st.calibration?['roi_px'] as List?)
        ?.map((p) => Offset(((p as List)[0] as num).toDouble(), (p[1] as num).toDouble()))
        .toList();
    Widget hud() => Hud(mode: st.mode, time: playback.time, countsAt: countsAt);
    Widget loading(String what) => AspectRatio(
          aspectRatio: r.width / r.height,
          child: Container(
            decoration: BoxDecoration(color: AppColors.neutralTint, borderRadius: BorderRadius.circular(10)),
            child: Center(child: Text('Loading $what…', style: t.bodySmall)),
          ),
        );
    Widget camera() => yolo == null
        ? loading('the YOLO detections')
        : CameraView(
            url: api.cameraUrl(runId),
            playback: playback,
            result: r,
            yolo: yolo,
            conf: st.conf,
            showBoxes: true,
            roi: roi,
            showRoi: st.showRoi,
            hud: hud(),
          );
    Widget lidar({Widget? hud}) => ld == null
        ? loading('the LiDAR results')
        : LidarView(data: ld, lagS: r.lagS, playback: playback, showBoxes: true, hud: hud,
            aspectRatio: r.width / r.height);
    final lag = r.lag;
    Widget lagNote() => lag == null
        ? const SizedBox.shrink()
        : Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(
              lag['source'] == 'none'
                  ? (lag['note'] as String? ?? '')
                  : 'LiDAR placed on the video timeline with lag ${(lag['lag_s'] as num).toStringAsFixed(2)} s '
                      '(${lag['source'] == 'manual' ? 'manual offset' : 'cross-correlation, r = ${lag['r']}'}'
                      '${lag['at_edge'] == true ? ', at the edge of the ±5 s window' : ''})'
                      '${ld?.zoneTiltDeg != null && ld!.zoneTiltDeg! > 10 ? ' · the Qb2 zone is tilted ${ld.zoneTiltDeg!.toStringAsFixed(0)}° from the floor normal: its footprint is drawn at 1.0 m (dashed), 0 m and 1.7 m (dotted)' : ''}',
              style: t.bodySmall?.copyWith(color: lag['source'] == 'none' ? amber : AppColors.textSecondary),
            ),
          );
    // Keep the view(s) within the screen height so the player stays visible on a laptop.
    final maxH = (MediaQuery.sizeOf(context).height - 330).clamp(340.0, 860.0);
    final aspect = r.width / r.height;
    Widget fit(Widget child, {double count = 1}) => LayoutBuilder(builder: (context, c) {
          final w = (maxH * aspect * count + 12 * (count - 1)).clamp(0.0, c.maxWidth);
          return Center(child: SizedBox(width: w, child: child));
        });
    switch (st.mode) {
      case LiveMode.lidar:
        return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [fit(lidar(hud: hud())), lagNote()]);
      case LiveMode.camera:
        return fit(camera());
      case LiveMode.fusion:
        return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          FusedBanner(time: playback.time, countsAt: countsAt),
          const SizedBox(height: 12),
          fit(count: 2, Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(child: camera()),
            const SizedBox(width: 12),
            Expanded(child: lidar()),
          ])),
          lagNote(),
        ]);
    }
  }
}
