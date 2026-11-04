import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../config.dart';

/// Overridden in main() with the loaded instance.
final prefsProvider = Provider<SharedPreferences>((ref) => throw UnimplementedError());

final apiProvider = Provider<ApiClient>((ref) => ApiClient(backendUrl));

final presetsProvider = FutureProvider<Presets>((ref) => ref.watch(apiProvider).presets());

/// Compute device (CPU / GPU) of the backend.
final systemProvider = FutureProvider<SystemInfo>((ref) => ref.watch(apiProvider).system());

// ------------------------------------------------------------------ backend health
/// true = connected, false = offline, null = not checked yet. Polls every 5 s.
class BackendHealth extends Notifier<bool?> {
  Timer? _timer;

  @override
  bool? build() {
    _timer = Timer.periodic(const Duration(seconds: 5), (_) => check());
    ref.onDispose(() => _timer?.cancel());
    Future.microtask(check);
    return null;
  }

  Future<void> check() async {
    try {
      await ref.read(apiProvider).health();
      if (ref.mounted) state = true;
    } on ApiException {
      if (ref.mounted) state = false;
    }
  }
}

final backendHealthProvider = NotifierProvider<BackendHealth, bool?>(BackendHealth.new);

// ------------------------------------------------------------------ runs list
class RunsNotifier extends AsyncNotifier<List<Run>> {
  Timer? _timer;

  @override
  Future<List<Run>> build() async {
    ref.onDispose(() => _timer?.cancel());
    final runs = await ref.read(apiProvider).listRuns();
    _schedule(runs);
    return runs;
  }

  void _schedule(List<Run> runs) {
    _timer?.cancel();
    if (runs.any((r) => r.active)) {
      _timer = Timer(const Duration(milliseconds: 1500), refresh);
    }
  }

  Future<void> refresh() async {
    try {
      final runs = await ref.read(apiProvider).listRuns();
      if (!ref.mounted) return;
      state = AsyncData(runs);
      _schedule(runs);
    } on ApiException catch (e, st) {
      if (ref.mounted) state = AsyncError(e, st);
    }
  }

  Future<void> delete(String id) async {
    await ref.read(apiProvider).deleteRun(id);
    await refresh();
  }

  Future<void> rerun(String id) async {
    await ref.read(apiProvider).rerun(id);
    await refresh();
  }
}

final runsProvider = AsyncNotifierProvider<RunsNotifier, List<Run>>(RunsNotifier.new, retry: (_, _) => null);

// ------------------------------------------------------------------ one run (polls while active)
class RunNotifier extends AsyncNotifier<Run> {
  RunNotifier(this.runId);
  final String runId;
  Timer? _timer;

  @override
  Future<Run> build() async {
    ref.onDispose(() => _timer?.cancel());
    final run = await ref.read(apiProvider).getRun(runId);
    _schedule(run);
    return run;
  }

  void _schedule(Run run) {
    _timer?.cancel();
    if (run.active) _timer = Timer(const Duration(milliseconds: 700), refresh);
  }

  Future<void> refresh() async {
    try {
      final run = await ref.read(apiProvider).getRun(runId);
      if (!ref.mounted) return;
      state = AsyncData(run);
      _schedule(run);
      if (!run.active) ref.invalidate(runsProvider);
    } on ApiException catch (e, st) {
      if (!ref.mounted) return;
      if (e.offline) {
        _timer = Timer(const Duration(seconds: 2), refresh); // keep trying
      } else {
        state = AsyncError(e, st);
      }
    }
  }

  /// Analyze / Retry / Rerun: the backend reuses cached steps.
  Future<void> rerun() async {
    state = AsyncData(await ref.read(apiProvider).rerun(runId));
    _schedule(state.requireValue);
    ref.invalidate(runsProvider);
  }

  Future<void> cancel() async {
    state = AsyncData(await ref.read(apiProvider).cancel(runId));
    _schedule(state.requireValue);
  }
}

final runProvider = AsyncNotifierProvider.autoDispose.family<RunNotifier, Run, String>(
  RunNotifier.new,
  retry: (_, _) => null,
);

// ------------------------------------------------------------------ Google Drive
class DriveNotifier extends AsyncNotifier<DriveStatus> {
  Timer? _poll;

  @override
  Future<DriveStatus> build() async {
    ref.onDispose(() => _poll?.cancel());
    final st = await ref.read(apiProvider).driveStatus();
    if (st.signinState == 'pending' && !st.signedIn) _startPolling();
    return st;
  }

  Future<void> refresh() async {
    try {
      final st = await ref.read(apiProvider).driveStatus();
      if (ref.mounted) state = AsyncData(st);
    } on ApiException catch (e, st) {
      if (ref.mounted) state = AsyncError(e, st);
    }
  }

  /// Starts the Google sign-in: opens Google's consent page in a new tab and
  /// polls the backend until the loopback redirect has been received.
  Future<String> signIn() async {
    final url = await ref.read(apiProvider).driveSignin();
    await launchUrl(Uri.parse(url), webOnlyWindowName: '_blank');
    await refresh();
    _startPolling();
    return url;
  }

  void _startPolling() {
    _poll?.cancel();
    _poll = Timer.periodic(const Duration(milliseconds: 1500), (t) async {
      await refresh();
      final st = state.value;
      if (st == null || st.signedIn || st.signinState != 'pending') t.cancel();
    });
  }

  Future<void> signOut() async {
    _poll?.cancel();
    state = AsyncData(await ref.read(apiProvider).driveSignout());
  }
}

final driveProvider = AsyncNotifierProvider<DriveNotifier, DriveStatus>(DriveNotifier.new, retry: (_, _) => null);
