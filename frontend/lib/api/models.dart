// Typed views over the backend JSON.

typedef Json = Map<String, dynamic>;

const roleLidarZip = 'lidar_zip';
const roleCameraVideo = 'camera_video';
const roleLidarScreen = 'lidar_screen';
const allRoles = [roleLidarZip, roleCameraVideo, roleLidarScreen];
const requiredRoles = [roleLidarZip, roleCameraVideo];

const roleLabels = {
  roleLidarZip: 'LiDAR recording (.zip)',
  roleCameraVideo: 'Camera video',
  roleLidarScreen: 'Sensor UI recording',
};

const roleShortLabels = {
  roleLidarZip: 'LiDAR',
  roleCameraVideo: 'Camera',
  roleLidarScreen: 'Sensor UI',
};

const activeStatuses = {'uploading', 'queued', 'downloading', 'validating', 'processing'};

class JobStep {
  JobStep(this.json);
  final Json json;
  String get key => json['key'] as String;
  String get label => json['label'] as String;
  String get state => json['state'] as String;
  double? get progress => (json['progress'] as num?)?.toDouble();
  num? get done => json['done'] as num?;
  num? get total => json['total'] as num?;
  String? get unit => json['unit'] as String?;
  String get message => (json['message'] as String?) ?? '';
  double? get etaS => (json['eta_s'] as num?)?.toDouble();
  double? get elapsedS => (json['elapsed_s'] as num?)?.toDouble();
}

class Job {
  Job(this.json);
  final Json json;
  String get state => json['state'] as String;
  String get kind => json['kind'] as String? ?? '';
  String? get error => json['error'] as String?;
  double? get progress => (json['progress'] as num?)?.toDouble();
  double? get elapsedS => (json['elapsed_s'] as num?)?.toDouble();
  double? get etaS => (json['eta_s'] as num?)?.toDouble();
  String? get failedStep => json['failed_step'] as String?;
  List<JobStep> get steps => [for (final s in (json['steps'] as List? ?? const [])) JobStep(s as Json)];
  bool get active => const {'created', 'queued', 'running'}.contains(state);
  JobStep? get currentStep {
    for (final s in steps) {
      if (s.state == 'running') return s;
    }
    return null;
  }
}

class RunFile {
  RunFile(this.role, this.json);
  final String role;
  final Json json;
  String get name => json['name'] as String;
  int? get size => (json['size'] as num?)?.toInt();
  String get status => json['status'] as String? ?? 'pending';
}

class CheckReport {
  CheckReport(this.json);
  final Json json;
  bool get ok => json['ok'] == true;
  List<String> get errors => [for (final e in (json['errors'] as List? ?? const [])) e.toString()];
  List<String> get warnings => [for (final e in (json['warnings'] as List? ?? const [])) e.toString()];
  Json get info => (json['info'] as Json?) ?? const {};
}

class GtSegment {
  const GtSegment(this.start, this.end, this.people);
  final Object start; // double (seconds) or "T" / "T-x"
  final Object end;
  final int people;

  factory GtSegment.fromJson(Json j) => GtSegment(j['start'] as Object, j['end'] as Object, (j['people'] as num).toInt());
  Json toJson() => {'start': start, 'end': end, 'people': people};
}

class GroundTruth {
  GroundTruth(this.preset, this.segments);
  final String? preset;
  final List<GtSegment> segments;
  factory GroundTruth.fromJson(Json j) => GroundTruth(
        j['preset'] as String?,
        [for (final s in (j['segments'] as List? ?? const [])) GtSegment.fromJson(s as Json)],
      );
}

class Run {
  Run(this.json);
  final Json json;
  String get id => json['id'] as String;
  String get name => json['name'] as String;
  String get createdAt => json['created_at'] as String? ?? '';
  String get status => json['status'] as String? ?? 'created';
  String? get error => json['error'] as String?;
  Json get source => (json['source'] as Json?) ?? const {};
  bool get isDrive => source['kind'] == 'drive';
  Job? get job => json['job'] == null ? null : Job(json['job'] as Json);
  bool get active => activeStatuses.contains(status) || (job?.active ?? false);
  Map<String, RunFile> get files => {
        for (final e in ((json['files'] as Json?) ?? const {}).entries) e.key: RunFile(e.key, e.value as Json),
      };
  GroundTruth? get groundTruth => json['ground_truth'] == null ? null : GroundTruth.fromJson(json['ground_truth'] as Json);
  Json? get validation => json['validation'] as Json?;
  CheckReport? check(String key) {
    final v = validation?[key];
    return v == null ? null : CheckReport(v as Json);
  }

  int get totalSize => files.values.fold(0, (a, f) => a + (f.size ?? 0));

  /// Processing summary (null until processed).
  Json? get results => json['results'] as Json?;

  /// Job of the Live view (mode runs and video exports).
  Job? get liveJob => json['live_job'] == null ? null : Job(json['live_job'] as Json);
  Json? get lastExport => json['last_export'] as Json?;
  bool get validated => (validation?['ok'] as bool?) ?? false;
}

class SystemInfo {
  SystemInfo(this.json);
  final Json json;
  bool get gpu => json['gpu'] == true;
  String get deviceLabel => json['device_label'] as String? ?? 'CPU';
  String? get error => json['error'] as String?;
  String get torch => json['torch'] as String? ?? '';
  String get ultralytics => json['ultralytics'] as String? ?? '';
}

class GtPreset {
  GtPreset(this.json);
  final Json json;
  String get key => json['key'] as String;
  String get label => json['label'] as String;
  String get description => json['description'] as String;
  String get source => json['source'] as String;
  List<GtSegment> get segments => [for (final s in json['segments'] as List) GtSegment.fromJson(s as Json)];
}

class Presets {
  Presets(this.json);
  final Json json;
  List<GtPreset> get groundTruth => [for (final p in json['ground_truth'] as List) GtPreset(p as Json)];
  Json get defaults => json['defaults'] as Json;
}

class DriveStatus {
  DriveStatus(this.json);
  final Json json;
  bool get clientConfigured => json['client_configured'] == true;
  String get clientMessage => json['client_message'] as String? ?? '';
  String get clientFile => json['client_file'] as String? ?? '';
  bool get signedIn => json['signed_in'] == true;
  Json? get account => json['account'] as Json?;
  String get email => account?['email'] as String? ?? '';
  String get displayName => account?['name'] as String? ?? '';
  Json get signin => (json['signin'] as Json?) ?? const {};
  String get signinState => signin['state'] as String? ?? 'idle';
  String? get signinError => signin['error'] as String?;
  String? get authUrl => signin['auth_url'] as String?;
}

class DriveFile {
  DriveFile(this.json);
  final Json json;
  String get id => json['id'] as String;
  String get name => json['name'] as String;
  int? get size => (json['size'] as num?)?.toInt();
  List<String> get candidateRoles => [for (final r in (json['candidate_roles'] as List? ?? const [])) r as String];
  Json toRef() => {'id': id, 'name': name, 'size': size};
}

class DriveListing {
  DriveListing(this.json);
  final Json json;
  Json get folder => json['folder'] as Json;
  String get folderId => folder['id'] as String;
  String get folderName => folder['name'] as String;
  String get folderPath => folder['path'] as String? ?? '';
  List<DriveFile> get files => [for (final f in json['files'] as List) DriveFile(f as Json)];
  List<String> get subfolders => [for (final f in (json['subfolders'] as List? ?? const [])) (f as Json)['name'] as String];
  Map<String, String?> get selection =>
      {for (final e in (json['selection'] as Json).entries) e.key: e.value as String?};
  List<String> get notes => [for (final n in (json['notes'] as List? ?? const [])) n.toString()];
  DriveFile? fileById(String? id) {
    if (id == null) return null;
    for (final f in files) {
      if (f.id == id) return f;
    }
    return null;
  }
}
