import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../state/providers.dart';
import 'live_models.dart';

class LiveState {
  const LiveState({
    this.loading = true,
    this.error,
    this.run,
    this.schema = const [],
    this.params = const {},
    this.mode = LiveMode.camera,
    this.resolved = const {},
    this.results = const {},
    this.yolo,
    this.lidar = const {},
    this.calibration,
    this.showRoi = true,
    this.actionError,
    this.dataLoading = false,
    this.resolving = false,
  });

  final bool loading;
  final String? error;
  final Run? run;
  final List<ParamSpec> schema;
  final Json params;
  final LiveMode mode;
  final Map<LiveMode, Json> resolved; // per mode, for the current parameters
  final Map<LiveMode, ModeResult> results; // last loaded result per mode (current or stale)
  final YoloData? yolo;
  final Map<String, LidarData> lidar;
  final Json? calibration;
  final bool showRoi;
  final String? actionError;
  final bool dataLoading;
  final bool resolving;

  LiveState copyWith({
    bool? loading,
    Object? error = _keep,
    Run? run,
    List<ParamSpec>? schema,
    Json? params,
    LiveMode? mode,
    Map<LiveMode, Json>? resolved,
    Map<LiveMode, ModeResult>? results,
    YoloData? yolo,
    Map<String, LidarData>? lidar,
    Json? calibration,
    bool? showRoi,
    Object? actionError = _keep,
    bool? dataLoading,
    bool? resolving,
  }) =>
      LiveState(
        loading: loading ?? this.loading,
        error: identical(error, _keep) ? this.error : error as String?,
        run: run ?? this.run,
        schema: schema ?? this.schema,
        params: params ?? this.params,
        mode: mode ?? this.mode,
        resolved: resolved ?? this.resolved,
        results: results ?? this.results,
        yolo: yolo ?? this.yolo,
        lidar: lidar ?? this.lidar,
        calibration: calibration ?? this.calibration,
        showRoi: showRoi ?? this.showRoi,
        actionError: identical(actionError, _keep) ? this.actionError : actionError as String?,
        dataLoading: dataLoading ?? this.dataLoading,
        resolving: resolving ?? this.resolving,
      );

  bool get hasGt => run?.groundTruth != null;
  bool available(LiveMode m) => resolved[m]?['available'] != false;
  String? unavailableReason(LiveMode m) => resolved[m]?['reason'] as String?;
  bool cached(LiveMode m) => resolved[m]?['cached'] == true;
  bool isCurrent(LiveMode m) => results[m] != null && resolved[m]?['key'] == results[m]!.key;
  bool isStale(LiveMode m) => results[m] != null && !isCurrent(m);
  ModeResult? get result => results[mode];
  Job? get liveJob => run?.liveJob;
  bool get busy => (liveJob?.active ?? false) || (run?.job?.active ?? false);
  LidarData? lidarFor(ModeResult? r) => r?.lidarKey == null ? null : lidar[r!.lidarKey];
  double get conf => ((params['yolo_conf'] as num?) ?? 0.25).toDouble();
  ParamSpec? spec(String key) => schema.where((s) => s.key == key).firstOrNull;

  /// LiDAR parameters that differ from the result shown in the current mode.
  bool get paramsChanged => isStale(mode);

  /// Parameters different from the best (notebook) values.
  int get nonBest => schema.where((s) => !s.equalsBest(params[s.key])).length;
}

const _keep = Object();

/// State of the Live view of one run.
class LiveController extends Notifier<LiveState> {
  LiveController(this.runId);
  final String runId;

  Timer? _poll;
  Timer? _debounce;
  final Map<String, Future<LidarData>> _lidarLoads = {};
  Future<YoloData>? _yoloLoad;
  LiveMode? _initialMode;

  ApiClient get _api => ref.read(apiProvider);

  @override
  LiveState build() {
    ref.onDispose(() {
      _poll?.cancel();
      _debounce?.cancel();
    });
    Future.microtask(_init);
    return const LiveState();
  }

  void setInitialMode(LiveMode? m) => _initialMode ??= m;

  Future<void> _init() async {
    try {
      final run = await _api.getRun(runId);
      if (!run.validated) {
        state = state.copyWith(loading: false, run: run,
            error: 'The inputs of this run are not validated yet. Open the run page and analyze it first.');
        return;
      }
      final schema = [for (final s in await _api.paramsSchema()) ParamSpec(s)];
      final params = await _api.getParams(runId);
      Json? calibration;
      try {
        calibration = await _api.calibration(runId);
      } on ApiException {
        calibration = null;
      }
      if (!ref.mounted) return;
      state = state.copyWith(run: run, schema: schema, params: params, calibration: calibration);
      await _resolveAll();
      if (!ref.mounted) return;
      final prefs = ref.read(prefsProvider);
      final remembered = LiveModeX.parse(prefs.getString('live.mode.$runId'));
      LiveMode pick() {
        for (final m in [_initialMode, remembered]) {
          if (m != null && state.available(m)) return m;
        }
        for (final m in [LiveMode.fusion, LiveMode.camera, LiveMode.lidar]) {
          if (state.available(m) && state.cached(m)) return m;
        }
        return LiveMode.camera;
      }

      state = state.copyWith(mode: pick(), loading: false);
      await _ensureData(state.mode);
      if (run.liveJob?.active ?? false) _startPolling();
    } on ApiException catch (e) {
      if (ref.mounted) state = state.copyWith(loading: false, error: e.message);
    }
  }

  Future<void> _resolveAll() async {
    state = state.copyWith(resolving: true);
    final resolved = Map<LiveMode, Json>.from(state.resolved);
    final results = Map<LiveMode, ModeResult>.from(state.results);
    await Future.wait([
      for (final m in LiveMode.values)
        _api.resolveMode(runId, m.key, state.params).then((r) {
          resolved[m] = r;
          if (r['cached'] == true && r['result'] != null) {
            results[m] = ModeResult(r['result'] as Json);
          } else if (results[m] == null && r['latest'] != null) {
            results[m] = ModeResult(r['latest'] as Json); // shown as "parameters changed, run again"
          }
        }),
    ]);
    if (!ref.mounted) return;
    state = state.copyWith(resolved: resolved, results: results, resolving: false);
  }

  Future<void> _ensureData(LiveMode m) async {
    final r = state.results[m];
    if (r == null) return;
    final needsLidar = m != LiveMode.camera && r.lidarKey != null && !state.lidar.containsKey(r.lidarKey);
    final needsYolo = m != LiveMode.lidar && state.yolo == null;
    if (!needsLidar && !needsYolo) return;
    state = state.copyWith(dataLoading: true);
    try {
      if (needsLidar) {
        final key = r.lidarKey!;
        final data = await (_lidarLoads[key] ??= () async {
          final j = await _api.lidarData(runId, key);
          final pts = await _api.lidarPoints(runId, key);
          return LidarData(j, pts);
        }());
        if (!ref.mounted) return;
        state = state.copyWith(lidar: {...state.lidar, key: data});
      }
      if (needsYolo) {
        final y = await (_yoloLoad ??= _api.yoloData(runId).then(YoloData.new));
        if (!ref.mounted) return;
        state = state.copyWith(yolo: y);
      }
    } on ApiException catch (e) {
      _lidarLoads.clear();
      _yoloLoad = null;
      if (ref.mounted) state = state.copyWith(actionError: e.message);
    } finally {
      if (ref.mounted) state = state.copyWith(dataLoading: false);
    }
  }

  // ---------------------------------------------------------------- mode
  Future<void> setMode(LiveMode m) async {
    if (!state.available(m)) return;
    state = state.copyWith(mode: m, actionError: null);
    ref.read(prefsProvider).setString('live.mode.$runId', m.key);
    await _ensureData(m);
  }

  // ---------------------------------------------------------------- parameters
  void setParam(String key, Object? value) {
    state = state.copyWith(params: {...state.params, key: value});
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 450), _commitParams);
  }

  void resetParam(String key) => setParam(key, state.spec(key)?.best);

  void resetAll({String? group}) {
    final p = Json.from(state.params);
    for (final s in state.schema) {
      if (group == null || s.group == group) p[s.key] = s.best;
    }
    state = state.copyWith(params: p);
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 150), _commitParams);
  }

  Future<void> _commitParams() async {
    try {
      final saved = await _api.putParams(runId, state.params); // remembered per run
      if (!ref.mounted) return;
      state = state.copyWith(params: {...state.params, ...saved}, actionError: null);
      await _resolveAll();
    } on ApiException catch (e) {
      if (ref.mounted) state = state.copyWith(actionError: e.message);
    }
  }

  void toggleRoi() => state = state.copyWith(showRoi: !state.showRoi);

  // ---------------------------------------------------------------- run / cancel / export
  Future<void> run() async {
    _debounce?.cancel();
    state = state.copyWith(actionError: null);
    try {
      await _api.putParams(runId, state.params);
      final res = await _api.runMode(runId, state.mode.key, state.params);
      if (!ref.mounted) return;
      state = state.copyWith(run: Run(res['run'] as Json));
      if (res['cached'] == true) {
        await _resolveAll();
        await _ensureData(state.mode);
      } else {
        _startPolling();
      }
    } on ApiException catch (e) {
      if (ref.mounted) state = state.copyWith(actionError: e.message);
    }
  }

  Future<void> cancel() async {
    try {
      state = state.copyWith(run: await _api.cancelLive(runId));
    } on ApiException catch (e) {
      state = state.copyWith(actionError: e.message);
    }
  }

  Future<void> exportVideo({required bool roi}) async {
    state = state.copyWith(actionError: null);
    try {
      state = state.copyWith(run: await _api.exportVideo(runId, state.mode.key, state.params, roi: roi));
      _startPolling();
    } on ApiException catch (e) {
      state = state.copyWith(actionError: e.message);
    }
  }

  void _startPolling() {
    _poll?.cancel();
    _poll = Timer.periodic(const Duration(milliseconds: 700), (t) async {
      try {
        final run = await _api.getRun(runId);
        if (!ref.mounted) return;
        state = state.copyWith(run: run);
        final job = run.liveJob;
        if (job == null || !job.active) {
          t.cancel();
          if (job != null && job.state == 'error') state = state.copyWith(actionError: job.error);
          if (job?.kind.startsWith('mode:') ?? false) {
            await _resolveAll();
            await _ensureData(state.mode);
          }
        }
      } on ApiException {
        // backend briefly unreachable: keep polling
      }
    });
  }
}

final liveProvider = NotifierProvider.autoDispose.family<LiveController, LiveState, String>(LiveController.new);
