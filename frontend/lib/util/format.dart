String formatBytes(num? bytes) {
  if (bytes == null) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  var v = bytes.toDouble();
  var i = 0;
  while (v >= 1000 && i < units.length - 1) {
    v /= 1000;
    i++;
  }
  final digits = i == 0 ? 0 : (v < 10 ? 2 : 1);
  return '${v.toStringAsFixed(digits)} ${units[i]}';
}

String formatEta(num? seconds) {
  if (seconds == null || seconds.isNaN || seconds.isInfinite) return '';
  final s = seconds.round();
  if (s < 5) return 'a few seconds left';
  if (s < 60) return '~$s s left';
  final m = (s / 60).round();
  if (m < 60) return '~$m min left';
  final h = s ~/ 3600;
  return '~$h h ${((s % 3600) / 60).round()} min left';
}

String formatSeconds(num? s, {int digits = 2}) => s == null ? '—' : '${s.toStringAsFixed(digits)} s';

/// 42 -> "0:42", 185 -> "3:05", 3723 -> "1:02:03".
String formatClock(num? seconds) {
  if (seconds == null) return '';
  final s = seconds.round();
  String two(int n) => n.toString().padLeft(2, '0');
  final h = s ~/ 3600, m = (s % 3600) ~/ 60, sec = s % 60;
  return h > 0 ? '$h:${two(m)}:${two(sec)}' : '$m:${two(sec)}';
}

/// "ETA 3 min", "ETA 40 s", "ETA a few s".
String formatEtaShort(num? seconds) {
  if (seconds == null || seconds.isNaN || seconds.isInfinite) return '';
  final s = seconds.round();
  if (s < 5) return 'ETA a few s';
  if (s < 60) return 'ETA $s s';
  final m = (s / 60).round();
  return m < 60 ? 'ETA $m min' : 'ETA ${s ~/ 3600} h ${((s % 3600) / 60).round()} min';
}

const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

String formatDateTime(String? iso) {
  if (iso == null) return '';
  final dt = DateTime.tryParse(iso)?.toLocal();
  if (dt == null) return iso;
  String two(int n) => n.toString().padLeft(2, '0');
  return '${dt.day} ${_months[dt.month - 1]} ${dt.year}, ${two(dt.hour)}:${two(dt.minute)}';
}

String formatInt(num n) {
  final s = n.round().toString();
  final b = StringBuffer();
  for (var i = 0; i < s.length; i++) {
    if (i > 0 && (s.length - i) % 3 == 0) b.write(',');
    b.write(s[i]);
  }
  return b.toString();
}

/// Display a ground-truth time token: 5.0 -> "5", "T-4" -> "T-4".
String formatToken(Object? t) {
  if (t is num) return t == t.roundToDouble() ? t.toInt().toString() : t.toString();
  return t?.toString() ?? '';
}
