import 'dart:math' as math;
import 'dart:typed_data';

import '../api/models.dart';

enum LiveMode { lidar, camera, fusion }

extension LiveModeX on LiveMode {
  String get key => name;
  String get label => switch (this) {
        LiveMode.lidar => 'LiDAR only',
        LiveMode.camera => 'Camera only (YOLO11m)',
        LiveMode.fusion => 'Fusion (LiDAR + Camera, Stack-GBT)',
      };
  String get short => switch (this) {
        LiveMode.lidar => 'LiDAR only',
        LiveMode.camera => 'Camera only',
        LiveMode.fusion => 'Fusion',
      };
  static LiveMode? parse(String? s) => LiveMode.values.where((m) => m.name == s).firstOrNull;
}

/// One editable parameter (from /api/params/schema). `best` = the notebook default.
class ParamSpec {
  ParamSpec(this.json);
  final Json json;
  String get key => json['key'] as String;
  String get group => json['group'] as String;
  String get section => json['section'] as String;
  String get label => json['label'] as String;
  String get kind => json['kind'] as String; // float | int | range | bool | offset
  String get unit => json['unit'] as String? ?? '';
  double get min => (json['min'] as num?)?.toDouble() ?? 0;
  double get max => (json['max'] as num?)?.toDouble() ?? 1;
  double get step => (json['step'] as num?)?.toDouble() ?? 0.01;
  String get help => json['help'] as String? ?? '';
  bool get instant => json['instant'] == true;
  Object? get best => json['best'];
  bool get isLidar => group == 'LiDAR';

  int get decimals {
    final s = step;
    if (s >= 1) return 0;
    return math.max(0, (-math.log(s) / math.ln10).ceil());
  }

  bool equalsBest(Object? v) => valuesEqual(v, best);

  static bool valuesEqual(Object? a, Object? b) {
    if (a is List && b is List) {
      return a.length == b.length && [for (var i = 0; i < a.length; i++) valuesEqual(a[i], b[i])].every((x) => x);
    }
    if (a is num && b is num) return (a - b).abs() < 1e-9;
    return a == b;
  }
}

/// Result of one mode run (`cache/modes/<mode>-<key>.json`).
class ModeResult {
  ModeResult(this.json);
  final Json json;
  LiveMode get mode => LiveModeX.parse(json['mode'] as String)!;
  String get key => json['key'] as String;
  Json get video => json['video'] as Json;
  double get T => (video['T'] as num).toDouble();
  double get fps => (video['fps'] as num).toDouble();
  int get frames => (video['frames'] as num).toInt();
  double get width => (video['width'] as num).toDouble();
  double get height => (video['height'] as num).toDouble();
  double get gridHz => (json['grid_hz'] as num).toDouble();
  Json get grid => json['grid'] as Json;
  List<double> get t => [for (final x in grid['t'] as List) (x as num).toDouble()];
  List<double?>? series(String k) =>
      grid[k] == null ? null : [for (final x in grid[k] as List) (x as num?)?.toDouble()];
  List<List<num>>? get gtSegments =>
      (json['gt_segments'] as List?)?.map((s) => [for (final v in s as List) v as num]).toList();
  Json get metrics => (json['metrics'] as Json?) ?? const {};
  Json get latency => (json['latency'] as Json?) ?? const {};
  Json? get lag => json['lag'] as Json?;
  double get lagS => ((lag?['lag_s']) as num?)?.toDouble() ?? 0;
  String? get lidarKey => json['lidar_key'] as String?;
  Json? get cv => json['cv'] as Json?;
  double? get conf => (json['conf'] as num?)?.toDouble();
}

/// Every YOLO person box per video frame (conf > 0.10), filtered in the browser.
class YoloData {
  YoloData(Json j)
      : key = j['key'] as String,
        summary = j['summary'] as Json,
        frames = [
          for (final f in j['frames'] as List)
            [for (final b in f as List) Float64List.fromList([for (final v in b as List) (v as num).toDouble()])]
        ];
  final String key;
  final Json summary;
  final List<List<Float64List>> frames; // [x1, y1, x2, y2, conf]
  double get fps => (summary['fps'] as num).toDouble();
  double get latencyMs => (summary['latency_ms_mean'] as num).toDouble();

  List<Float64List> boxesAt(int frame, double conf) =>
      frame < 0 || frame >= frames.length ? const [] : [for (final b in frames[frame]) if (b[4] > conf) b];

  /// Count per frame at `conf` (the notebook's YOLO count: boxes with conf > threshold).
  List<double> counts(double conf) => [for (final f in frames) f.where((b) => b[4] > conf).length.toDouble()];
}

class LidarCluster {
  LidarCluster(List l)
      : u = (l[0] as num).toDouble(),
        v = (l[1] as num).toDouble(),
        w = (l[2] as num).toDouble(),
        d = (l[3] as num).toDouble(),
        top = (l[4] as num).toDouble(),
        n = (l[5] as num).toInt(),
        trackId = (l[6] as num?)?.toInt(),
        confirmed = l[7] == true;
  final double u, v, w, d, top;
  final int n;
  final int? trackId;
  final bool confirmed;
}

class LidarFrame {
  LidarFrame(Json j)
      : t = (j['t'] as num).toDouble(),
        raw = (j['raw'] as num).toInt(),
        tracked = (j['tracked'] as num).toInt(),
        smooth = (j['smooth'] as num).toInt(),
        clusters = [for (final c in j['c'] as List) LidarCluster(c as List)];
  final double t; // seconds from the first LiDAR frame
  final int raw, tracked, smooth;
  final List<LidarCluster> clusters;
}

/// LiDAR results of one parameter set: frames, foreground points, scene.
class LidarData {
  LidarData(Json j, Uint8List points)
      : key = j['key'] as String,
        summary = j['summary'] as Json,
        frames = [for (final f in j['frames'] as List) LidarFrame(f as Json)],
        background = Float32List.fromList([
          for (final p in (j['scene'] as Json)['background'] as List) ...[
            ((p as List)[0] as num) / 100.0,
            (p[1] as num) / 100.0,
          ]
        ]),
        zone = [
          for (final c in ((j['scene'] as Json)['zone'] as Json)['outline'] as List)
            [((c as List)[0] as num).toDouble(), (c[1] as num).toDouble()]
        ],
        zoneOthers = [
          for (final e in ((((j['scene'] as Json)['zone'] as Json)['outlines'] as Json?) ?? const {}).entries)
            if (e.key != '1.0')
              [for (final c in e.value as List) [((c as List)[0] as num).toDouble(), (c[1] as num).toDouble()]]
        ],
        zoneTiltDeg = (((j['scene'] as Json)['zone'] as Json)['tilt_deg'] as num?)?.toDouble() {
    final bytes = Uint8List.fromList(points); // own buffer, aligned
    final bd = ByteData.sublistView(bytes);
    final n = bd.getUint32(0, Endian.little);
    offsets = Uint32List(n + 1);
    for (var i = 0; i <= n; i++) {
      offsets[i] = bd.getUint32(4 + 4 * i, Endian.little);
    }
    final start = 4 * (n + 2);
    pointsCm = bytes.buffer.asInt16List(start, (bytes.length - start) ~/ 2);
  }

  final String key;
  final Json summary;
  final List<LidarFrame> frames;
  final Float32List background; // (u, v) pairs, metres
  final List<List<double>> zone; // footprint at 1.0 m
  final List<List<List<double>>> zoneOthers; // footprints at 0 and 1.7 m
  final double? zoneTiltDeg;
  late final Uint32List offsets;
  late final Int16List pointsCm; // (u, v, h) cm

  double get periodS => 1.0 / (((summary['rate_hz'] as num?)?.toDouble()) ?? 7.8);
  double get latencyMs => (summary['latency_ms_mean'] as num).toDouble();

  /// Index of the LiDAR frame shown at LiDAR time tl (the latest at or before tl).
  int? frameAt(double tl) {
    if (frames.isEmpty || tl < frames.first.t || tl > frames.last.t + periodS) return null;
    var lo = 0, hi = frames.length - 1;
    while (lo < hi) {
      final mid = (lo + hi + 1) >> 1;
      if (frames[mid].t <= tl) {
        lo = mid;
      } else {
        hi = mid - 1;
      }
    }
    return lo;
  }
}

// ---------------------------------------------------------------- notebook ports (sensors_fusion.ipynb)

/// Port of resample_counts (cell 5): idx = clip(searchsorted(ts, t_grid), 1, len(ts) - 1).
List<double> resampleCounts(List<double> ts, List<double> cs, List<double> tGrid) {
  int searchsortedLeft(double x) {
    var lo = 0, hi = ts.length;
    while (lo < hi) {
      final mid = (lo + hi) >> 1;
      if (ts[mid] < x) {
        lo = mid + 1;
      } else {
        hi = mid;
      }
    }
    return lo;
  }

  return [for (final t in tGrid) cs[searchsortedLeft(t).clamp(1, ts.length - 1)]];
}

/// Port of counting_metrics (cell 16). Values in percent like the notebook.
Map<String, double> countingMetrics(List<double> pred, List<double> gt) {
  var tp = 0.0, fp = 0.0, fn = 0.0, absErr = 0.0, sqErr = 0.0, err = 0.0, exact = 0, within = 0;
  for (var i = 0; i < pred.length; i++) {
    final p = pred[i], g = gt[i], e = p - g;
    tp += math.min(p, g);
    fp += math.max(p - g, 0);
    fn += math.max(g - p, 0);
    absErr += e.abs();
    sqErr += e * e;
    err += e;
    if (e == 0) exact++;
    if (e.abs() <= 1) within++;
  }
  final n = pred.length.toDouble();
  final P = tp + fp > 0 ? tp / (tp + fp) : 0.0;
  final R = tp + fn > 0 ? tp / (tp + fn) : 0.0;
  final F = P + R > 0 ? 2 * P * R / (P + R) : 0.0;
  return {
    'Precision': 100 * P,
    'Recall': 100 * R,
    'F1 Score': 100 * F,
    'MAE': absErr / n,
    'RMSE': math.sqrt(sqErr / n),
    'Bias': err / n,
    'Exact %': 100 * exact / n,
    'Within ±1 %': 100 * within / n,
  };
}

const metricKeys = ['Precision', 'Recall', 'F1 Score', 'MAE', 'RMSE', 'Bias', 'Exact %', 'Within ±1 %'];

/// The GT segment shown at t, as draw_phase_label (cell 15): the first segment with s <= t < e.
List<num>? gtPhaseAt(List<List<num>>? segs, double t) {
  if (segs == null) return null;
  for (final s in segs) {
    if (s[0] <= t && t < s[1]) return s;
  }
  return null;
}

/// to_grid_idx (cell 15): clip(round(t * GRID_HZ), 0, len - 1).
int gridIndex(double t, double hz, int n) => (t * hz).round().clamp(0, n - 1);
