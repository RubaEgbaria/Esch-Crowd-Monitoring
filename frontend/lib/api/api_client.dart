import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import 'models.dart';

/// An error with a message that can be shown to the user as-is.
class ApiException implements Exception {
  ApiException(this.status, this.code, this.message, [this.details = const {}]);
  final int status;
  final String code;
  final String message;
  final Json details;

  bool get offline => status == 0;

  @override
  String toString() => message;
}

class ApiClient {
  ApiClient(this.baseUrl, {http.Client? client}) : _http = client ?? http.Client();

  final String baseUrl;
  final http.Client _http;

  Uri _uri(String path, [Map<String, String>? query]) =>
      Uri.parse('$baseUrl$path').replace(queryParameters: query);

  Future<dynamic> _send(
    String method,
    String path, {
    Object? json,
    Uint8List? bytes,
    Map<String, String>? query,
  }) async {
    final req = http.Request(method, _uri(path, query));
    if (json != null) {
      req.headers['Content-Type'] = 'application/json';
      req.body = jsonEncode(json);
    } else if (bytes != null) {
      req.headers['Content-Type'] = 'application/octet-stream';
      req.bodyBytes = bytes;
    }
    http.Response res;
    try {
      res = await http.Response.fromStream(await _http.send(req));
    } on http.ClientException {
      throw ApiException(0, 'offline', 'Cannot reach the backend at $baseUrl. Is it running?');
    }
    if (res.statusCode == 204 || res.body.isEmpty) return null;
    dynamic body;
    try {
      body = jsonDecode(utf8.decode(res.bodyBytes));
    } on FormatException {
      body = null;
    }
    if (res.statusCode >= 400) {
      if (body is Map && body['error'] is Map) {
        final e = body['error'] as Map;
        throw ApiException(res.statusCode, '${e['code']}', '${e['message']}',
            (e['details'] as Map?)?.cast<String, dynamic>() ?? const {});
      }
      if (body is Map && body['detail'] != null) {
        throw ApiException(res.statusCode, 'error', '${body['detail']}');
      }
      throw ApiException(res.statusCode, 'error', 'Request failed (${res.statusCode}).');
    }
    return body;
  }

  // ---------------------------------------------------------------- meta
  Future<Json> health() async => await _send('GET', '/api/health') as Json;
  Future<Presets> presets() async => Presets(await _send('GET', '/api/presets') as Json);

  // ---------------------------------------------------------------- runs
  Future<List<Run>> listRuns() async =>
      [for (final r in await _send('GET', '/api/runs') as List) Run(r as Json)];
  Future<Run> getRun(String id) async => Run(await _send('GET', '/api/runs/$id') as Json);
  Future<Run> createRun(Json body) async => Run(await _send('POST', '/api/runs', json: body) as Json);
  Future<void> deleteRun(String id) async => _send('DELETE', '/api/runs/$id');
  Future<Run> rerun(String id, {bool force = false}) async =>
      Run(await _send('POST', '/api/runs/$id/rerun', query: force ? {'force': 'true'} : null) as Json);
  Future<Run> analyze(String id) async => Run(await _send('POST', '/api/runs/$id/analyze') as Json);
  Future<SystemInfo> system() async => SystemInfo(await _send('GET', '/api/system') as Json);
  String mediaUrl(String id, String role) => '$baseUrl/api/runs/$id/media/$role';
  Future<Run> cancel(String id) async => Run(await _send('POST', '/api/runs/$id/cancel') as Json);
  Future<Run> startRun(String id) async => Run(await _send('POST', '/api/runs/$id/start') as Json);

  Future<Json> uploadChunk(String id, String role, int offset, Uint8List data) async =>
      await _send('PUT', '/api/runs/$id/files/$role/chunk', bytes: data, query: {'offset': '$offset'}) as Json;
  Future<Run> completeUpload(String id, String role) async =>
      Run(await _send('POST', '/api/runs/$id/files/$role/complete') as Json);

  // ---------------------------------------------------------------- live view
  Future<List<Json>> paramsSchema() async =>
      [for (final s in await _send('GET', '/api/params/schema') as List) s as Json];
  Future<Json> getParams(String id) async => await _send('GET', '/api/runs/$id/params') as Json;
  Future<Json> putParams(String id, Json params) async =>
      await _send('PUT', '/api/runs/$id/params', json: params) as Json;
  Future<Json> resolveMode(String id, String mode, Json params) async =>
      await _send('POST', '/api/runs/$id/modes/$mode/resolve', json: {'params': params}) as Json;
  Future<Json> runMode(String id, String mode, Json params) async =>
      await _send('POST', '/api/runs/$id/modes/$mode/run', json: {'params': params}) as Json;
  Future<Run> cancelLive(String id) async => Run(await _send('POST', '/api/runs/$id/live/cancel') as Json);
  Future<Json> yoloData(String id) async => await _send('GET', '/api/runs/$id/data/yolo') as Json;
  Future<Json> lidarData(String id, String key) async => await _send('GET', '/api/runs/$id/data/lidar/$key') as Json;
  Future<Json> calibration(String id) async => await _send('GET', '/api/runs/$id/calibration') as Json;
  Future<Run> exportVideo(String id, String mode, Json params, {required bool roi}) async =>
      Run(await _send('POST', '/api/runs/$id/modes/$mode/export-video', json: {'params': params, 'roi': roi}) as Json);

  Future<Uint8List> lidarPoints(String id, String key) async {
    try {
      final res = await _http.get(_uri('/api/runs/$id/data/lidar/$key/points'));
      if (res.statusCode != 200) throw ApiException(res.statusCode, 'error', 'Could not load the LiDAR points.');
      return res.bodyBytes;
    } on http.ClientException {
      throw ApiException(0, 'offline', 'Cannot reach the backend at $baseUrl. Is it running?');
    }
  }

  String cameraUrl(String id) => '$baseUrl/api/runs/$id/media/camera';
  String exportResultsUrl(String id, String mode, String format, Json params) =>
      _uri('/api/runs/$id/modes/$mode/export', {'format': format, 'params': jsonEncode(params)}).toString();
  String exportFileUrl(String id, String name) => '$baseUrl/api/runs/$id/exports/$name';

  // ---------------------------------------------------------------- drive
  Future<DriveStatus> driveStatus() async => DriveStatus(await _send('GET', '/api/drive/status') as Json);
  Future<String> driveSignin() async => (await _send('POST', '/api/drive/signin') as Json)['auth_url'] as String;
  Future<DriveStatus> driveSignout() async => DriveStatus(await _send('POST', '/api/drive/signout') as Json);
  Future<DriveListing> driveResolve(String query) async =>
      DriveListing(await _send('POST', '/api/drive/resolve', json: {'query': query}) as Json);
}
