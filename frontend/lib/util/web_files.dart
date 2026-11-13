import 'dart:async';
import 'dart:js_interop';
import 'dart:typed_data';

import 'package:web/web.dart' as web;

import '../api/api_client.dart';

/// A file chosen in the browser. Its bytes are read lazily, slice by slice.
class PickedFile {
  PickedFile(this.file);
  final web.File file;
  String get name => file.name;
  int get size => file.size;

  Future<Uint8List> readRange(int start, int end) async {
    final buf = await file.slice(start, end).arrayBuffer().toDart;
    return buf.toDart.asUint8List();
  }
}

/// Opens the browser's file dialog. Resolves to null if the user cancels.
Future<PickedFile?> pickFile({required String accept}) {
  final completer = Completer<PickedFile?>();
  final input = web.HTMLInputElement()
    ..type = 'file'
    ..accept = accept;
  input.addEventListener(
    'change',
    ((web.Event _) {
      final files = input.files;
      if (!completer.isCompleted) {
        completer.complete(files != null && files.length > 0 ? PickedFile(files.item(0)!) : null);
      }
    }).toJS,
  );
  input.addEventListener(
    'cancel',
    ((web.Event _) {
      if (!completer.isCompleted) completer.complete(null);
    }).toJS,
  );
  input.click();
  return completer.future;
}

const int uploadChunkBytes = 8 * 1024 * 1024;

/// Sends [file] to the backend in chunks; resumes from the server's offset
/// after a mismatch and retries transient network errors.
Future<void> uploadFile(
  ApiClient api,
  String runId,
  String role,
  PickedFile file, {
  required void Function(int sentBytes) onProgress,
  bool Function()? isCancelled,
}) async {
  var offset = 0;
  var failures = 0;
  while (offset < file.size) {
    if (isCancelled?.call() ?? false) throw ApiException(499, 'cancelled', 'Upload cancelled.');
    final end = (offset + uploadChunkBytes).clamp(0, file.size);
    final chunk = await file.readRange(offset, end);
    try {
      final res = await api.uploadChunk(runId, role, offset, chunk);
      offset = (res['received'] as num).toInt();
      failures = 0;
      onProgress(offset);
    } on ApiException catch (e) {
      if (e.code == 'offset_mismatch' && e.details['expected_offset'] is num) {
        offset = (e.details['expected_offset'] as num).toInt();
        continue;
      }
      if (e.offline && ++failures <= 3) {
        await Future<void>.delayed(Duration(seconds: 2 * failures));
        continue;
      }
      rethrow;
    }
  }
  await api.completeUpload(runId, role);
}
