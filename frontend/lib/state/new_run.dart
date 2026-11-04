import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../util/format.dart';
import '../util/web_files.dart';
import 'providers.dart';

enum SourceKind { drive, upload }

/// One editable ground-truth row (raw text, validated on the fly).
class SegmentDraft {
  const SegmentDraft(this.start, this.end, this.people);
  final String start;
  final String end;
  final String people;

  factory SegmentDraft.fromSegment(GtSegment s) =>
      SegmentDraft(formatToken(s.start), formatToken(s.end), '${s.people}');

  SegmentDraft copyWith({String? start, String? end, String? people}) =>
      SegmentDraft(start ?? this.start, end ?? this.end, people ?? this.people);

  static final _token = RegExp(r'^\s*(\d+(\.\d*)?|\.\d+|[Tt](\s*-\s*(\d+(\.\d*)?|\.\d+))?)\s*$');

  static String? tokenError(String v) =>
      _token.hasMatch(v) ? null : (v.trim().isEmpty ? 'Required' : 'Seconds, T or T-x');

  static String? peopleError(String v) {
    final n = int.tryParse(v.trim());
    return n == null || n < 0 ? 'Whole number ≥ 0' : null;
  }

  bool get valid => tokenError(start) == null && tokenError(end) == null && peopleError(people) == null;

  static Object tokenValue(String v) {
    final s = v.trim().replaceAll(' ', '').toUpperCase();
    return double.tryParse(s) ?? s;
  }

  Json toJson() => {'start': tokenValue(start), 'end': tokenValue(end), 'people': int.parse(people.trim())};
  List<String> toList() => [start, end, people];
}

const _unset = Object();

const _inSentence = {
  roleLidarZip: 'LiDAR recording (.zip)',
  roleCameraVideo: 'camera video',
  roleLidarScreen: 'sensor UI recording',
};

class NewRunState {
  const NewRunState({
    this.name = '',
    this.nameEdited = false,
    this.source = SourceKind.drive,
    this.driveQuery = '',
    this.resolving = false,
    this.resolveError,
    this.listing,
    this.selection = const {},
    this.uploads = const {},
    this.gtEnabled = false,
    this.gtPreset,
    this.segments = const [],
    this.submitting = false,
    this.submitError,
    this.runId,
  });

  final String name;
  final bool nameEdited;
  final SourceKind source;
  final String driveQuery;
  final bool resolving;
  final String? resolveError;
  final DriveListing? listing;
  final Map<String, String?> selection; // role -> Drive file id
  final Map<String, PickedFile> uploads; // role -> picked browser file
  final bool gtEnabled;
  final String? gtPreset; // null = custom
  final List<SegmentDraft> segments;
  final bool submitting;
  final String? submitError;
  final String? runId; // set once "Analyze" created the run

  NewRunState copyWith({
    String? name,
    bool? nameEdited,
    SourceKind? source,
    String? driveQuery,
    bool? resolving,
    Object? resolveError = _unset,
    Object? listing = _unset,
    Map<String, String?>? selection,
    Map<String, PickedFile>? uploads,
    bool? gtEnabled,
    Object? gtPreset = _unset,
    List<SegmentDraft>? segments,
    bool? submitting,
    Object? submitError = _unset,
    Object? runId = _unset,
  }) =>
      NewRunState(
        name: name ?? this.name,
        nameEdited: nameEdited ?? this.nameEdited,
        source: source ?? this.source,
        driveQuery: driveQuery ?? this.driveQuery,
        resolving: resolving ?? this.resolving,
        resolveError: identical(resolveError, _unset) ? this.resolveError : resolveError as String?,
        listing: identical(listing, _unset) ? this.listing : listing as DriveListing?,
        selection: selection ?? this.selection,
        uploads: uploads ?? this.uploads,
        gtEnabled: gtEnabled ?? this.gtEnabled,
        gtPreset: identical(gtPreset, _unset) ? this.gtPreset : gtPreset as String?,
        segments: segments ?? this.segments,
        submitting: submitting ?? this.submitting,
        submitError: identical(submitError, _unset) ? this.submitError : submitError as String?,
        runId: identical(runId, _unset) ? this.runId : runId as String?,
      );

  DriveFile? selectedDriveFile(String role) => listing?.fileById(selection[role]);

  int get downloadBytes => [for (final r in allRoles) selectedDriveFile(r)?.size ?? 0].fold(0, (a, b) => a + b);
  int get uploadBytes => uploads.values.fold(0, (a, f) => a + f.size);

  /// Reasons why "Analyze" is disabled (empty = ready).
  List<String> problems({required bool driveSignedIn}) {
    final p = <String>[];
    if (name.trim().isEmpty) p.add('Give the run a name.');
    if (source == SourceKind.drive) {
      if (!driveSignedIn) {
        p.add('Sign in with Google.');
      } else if (listing == null) {
        p.add('Find the files of a Drive folder.');
      } else {
        for (final r in requiredRoles) {
          if (selectedDriveFile(r) == null) p.add('Select the ${_inSentence[r]}.');
        }
      }
    } else {
      for (final r in requiredRoles) {
        if (!uploads.containsKey(r)) p.add('Choose the ${_inSentence[r]}.');
      }
    }
    if (gtEnabled) {
      if (segments.isEmpty) p.add('Add a ground-truth segment or turn ground truth off.');
      if (segments.any((s) => !s.valid)) p.add('Fix the highlighted ground-truth values.');
    }
    return p;
  }
}

class NewRunController extends Notifier<NewRunState> {
  static const _kQuery = 'newrun.driveQuery';
  static const _kSource = 'newrun.source';
  static const _kGtEnabled = 'newrun.gtEnabled';
  static const _kGtPreset = 'newrun.gtPreset';
  static const _kGtSegments = 'newrun.gtSegments';

  bool _cancelUpload = false;

  @override
  NewRunState build() {
    final prefs = ref.read(prefsProvider);
    var segments = <SegmentDraft>[];
    final raw = prefs.getString(_kGtSegments);
    if (raw != null) {
      try {
        segments = [
          for (final s in jsonDecode(raw) as List)
            SegmentDraft('${(s as List)[0]}', '${s[1]}', '${s[2]}'),
        ];
      } on Object {
        segments = [];
      }
    }
    return NewRunState(
      driveQuery: prefs.getString(_kQuery) ?? '',
      source: prefs.getString(_kSource) == 'upload' ? SourceKind.upload : SourceKind.drive,
      gtEnabled: prefs.getBool(_kGtEnabled) ?? false,
      gtPreset: prefs.getString(_kGtPreset),
      segments: segments,
    );
  }

  void _saveGt() {
    final prefs = ref.read(prefsProvider);
    prefs.setBool(_kGtEnabled, state.gtEnabled);
    if (state.gtPreset == null) {
      prefs.remove(_kGtPreset);
    } else {
      prefs.setString(_kGtPreset, state.gtPreset!);
    }
    prefs.setString(_kGtSegments, jsonEncode([for (final s in state.segments) s.toList()]));
  }

  // ---------------------------------------------------------------- basics
  void setName(String v) => state = state.copyWith(name: v, nameEdited: v.trim().isNotEmpty);

  void _suggestName(String suggestion) {
    if (!state.nameEdited) state = state.copyWith(name: suggestion);
  }

  void setSource(SourceKind s) {
    state = state.copyWith(source: s);
    ref.read(prefsProvider).setString(_kSource, s.name);
    if (s == SourceKind.drive && state.listing != null) _suggestName(state.listing!.folderName);
    if (s == SourceKind.upload && state.uploads[roleLidarZip] != null) {
      _suggestName(_stem(state.uploads[roleLidarZip]!.name));
    }
  }

  static String _stem(String n) => n.contains('.') ? n.substring(0, n.lastIndexOf('.')) : n;

  // ---------------------------------------------------------------- Drive
  void setDriveQuery(String v) => state = state.copyWith(driveQuery: v);

  Future<void> resolve() async {
    final q = state.driveQuery.trim();
    if (q.isEmpty) return;
    state = state.copyWith(resolving: true, resolveError: null, listing: null, selection: const {});
    ref.read(prefsProvider).setString(_kQuery, q);
    try {
      final listing = await ref.read(apiProvider).driveResolve(q);
      state = state.copyWith(resolving: false, listing: listing, selection: listing.selection);
      _suggestName(listing.folderName);
    } on ApiException catch (e) {
      state = state.copyWith(resolving: false, resolveError: e.message);
      if (e.code == 'drive_not_signed_in') ref.invalidate(driveProvider);
    }
  }

  void select(String role, String? fileId) =>
      state = state.copyWith(selection: {...state.selection, role: fileId});

  // ---------------------------------------------------------------- upload
  Future<void> pick(String role) async {
    final accept = switch (role) {
      roleLidarZip => '.zip',
      roleCameraVideo => '.mp4,.m4v,.mov,.avi,.mkv,video/*',
      _ => '.mp4,.m4v,.webm,.mov',
    };
    final f = await pickFile(accept: accept);
    if (f == null) return;
    state = state.copyWith(uploads: {...state.uploads, role: f});
    if (role == roleLidarZip) _suggestName(_stem(f.name));
  }

  void clearUpload(String role) =>
      state = state.copyWith(uploads: {...state.uploads}..remove(role));

  // ---------------------------------------------------------------- ground truth
  void setGtEnabled(bool on, {GtPreset? defaultPreset}) {
    state = state.copyWith(gtEnabled: on);
    if (on && state.segments.isEmpty && defaultPreset != null) {
      applyPreset(defaultPreset);
      return;
    }
    _saveGt();
  }

  void applyPreset(GtPreset p) {
    state = state.copyWith(
      gtEnabled: true,
      gtPreset: p.key,
      segments: [for (final s in p.segments) SegmentDraft.fromSegment(s)],
    );
    _saveGt();
  }

  void setCustom() {
    state = state.copyWith(gtPreset: null);
    _saveGt();
  }

  void editSegment(int i, {String? start, String? end, String? people}) {
    final segs = [...state.segments];
    segs[i] = segs[i].copyWith(start: start, end: end, people: people);
    state = state.copyWith(segments: segs, gtPreset: null);
    _saveGt();
  }

  void addSegment() {
    final last = state.segments.isEmpty ? null : state.segments.last;
    state = state.copyWith(
      segments: [...state.segments, SegmentDraft(last?.end ?? '0', 'T', last?.people ?? '0')],
      gtPreset: null,
    );
    _saveGt();
  }

  void removeSegment(int i) {
    state = state.copyWith(segments: [...state.segments]..removeAt(i), gtPreset: null);
    _saveGt();
  }

  // ---------------------------------------------------------------- analyze
  Json _body() {
    final body = <String, dynamic>{
      'name': state.name.trim(),
      'source': state.source.name,
    };
    if (state.gtEnabled) {
      body['ground_truth'] = {
        'preset': state.gtPreset,
        'segments': [for (final s in state.segments) s.toJson()],
      };
    }
    if (state.source == SourceKind.drive) {
      final l = state.listing!;
      body['drive_folder'] = {'id': l.folderId, 'name': l.folderName, 'path': l.folderPath, 'query': state.driveQuery};
      body['drive_files'] = {
        for (final r in allRoles)
          if (state.selectedDriveFile(r) != null) r: state.selectedDriveFile(r)!.toRef(),
      };
    } else {
      body['upload_files'] = {
        for (final e in state.uploads.entries) e.key: {'name': e.value.name, 'size': e.value.size},
      };
    }
    return body;
  }

  Future<void> analyze() async {
    final api = ref.read(apiProvider);
    // Capture the inputs: the form may be reset while the upload continues.
    final source = state.source;
    final uploads = Map.of(state.uploads);
    final body = _body();
    _cancelUpload = false;
    state = state.copyWith(submitting: true, submitError: null);
    String? runId;
    try {
      final run = await api.createRun(body);
      runId = run.id;
      state = state.copyWith(runId: runId);
      ref.invalidate(runsProvider);
      if (source == SourceKind.upload) {
        for (final role in allRoles) {
          final f = uploads[role];
          if (f == null) continue;
          await uploadFile(api, runId, role, f, onProgress: (_) {}, isCancelled: () => _cancelUpload);
        }
        await api.startRun(runId);
      }
    } on ApiException catch (e) {
      state = state.copyWith(submitError: e.message);
      if (runId != null && source == SourceKind.upload && e.code != 'cancelled') {
        try {
          await api.cancel(runId); // don't leave the run stuck in "uploading"
        } on ApiException {
          // already finished or gone
        }
      }
    } finally {
      state = state.copyWith(submitting: false);
      if (runId != null) ref.invalidate(runProvider(runId));
    }
  }

  Future<void> cancelRun() async {
    final id = state.runId;
    if (id == null) return;
    _cancelUpload = true;
    try {
      await ref.read(apiProvider).cancel(id);
    } on ApiException {
      // finished meanwhile
    }
    ref.invalidate(runProvider(id));
  }

  /// Back to the form, keeping the inputs (e.g. after an error).
  void backToForm() => state = state.copyWith(runId: null, submitError: null);

  /// Fresh form for another run (keeps the remembered Drive path and GT).
  void startOver() {
    final keep = state;
    state = NewRunState(
      source: keep.source,
      driveQuery: keep.driveQuery,
      gtEnabled: keep.gtEnabled,
      gtPreset: keep.gtPreset,
      segments: keep.segments,
    );
  }
}

final newRunProvider = NotifierProvider<NewRunController, NewRunState>(NewRunController.new);
