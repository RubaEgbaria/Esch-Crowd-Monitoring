import 'dart:js_interop';

import 'package:flutter/foundation.dart';
import 'package:web/web.dart' as web;

/// One shared clock on the video timeline [0, T] for every view.
///
/// When a camera view is on screen its `<video>` element is the master clock
/// (the overlays read `currentTime` on every animation frame, so they stay in
/// sync with the decoded frame). Without a video (LiDAR only) a ticker
/// advances the time. Nothing is processed during replay.
class PlaybackController extends ChangeNotifier {
  PlaybackController({required this.duration, required this.fps});

  double duration;
  double fps; // camera fps (frame stepping on the camera timeline)

  final ValueNotifier<double> time = ValueNotifier(0);
  bool playing = false;
  double speed = 1.0;
  bool loop = true;

  web.HTMLVideoElement? _video;
  Duration? _lastTick;
  double? _pendingSeek; // a seek requested before the video could take it
  List<double>? stepTimes; // custom frame-step positions (LiDAR frames in video time)

  bool get hasVideo => _video != null;

  void attachVideo(web.HTMLVideoElement v) {
    _video = v;
    _pendingSeek = time.value; // the new video starts at 0: bring it to the current time
    v.playbackRate = speed;
    v.muted = true;
    void sync(web.Event _) {
      if (_video != v) return;
      if ((v.currentTime - time.value).abs() > 0.05) v.currentTime = time.value;
      if (playing) v.play().toDart.catchError((_) => null);
    }

    v.addEventListener('loadedmetadata', sync.toJS);
    v.addEventListener(
      'ended',
      ((web.Event _) {
        if (_video != v) return;
        if (loop) {
          seek(0);
          if (playing) v.play().toDart.catchError((_) => null);
        } else {
          _setPlaying(false);
        }
      }).toJS,
    );
  }

  void detachVideo(web.HTMLVideoElement v) {
    if (_video == v) {
      v.pause();
      _video = null;
    }
  }

  /// Called on every animation frame.
  void tick(Duration elapsed) {
    final last = _lastTick;
    _lastTick = elapsed;
    final v = _video;
    if (v != null && v.readyState >= 1) {
      final pending = _pendingSeek;
      if (pending != null) {
        _pendingSeek = null;
        v.currentTime = pending;
        time.value = pending;
        return;
      }
      final t = v.currentTime.toDouble();
      if ((t - time.value).abs() > 1e-4) time.value = t.clamp(0, duration);
      if (playing && v.paused && !v.ended && !v.seeking) {
        v.play().toDart.catchError((_) => null);
      }
      return;
    }
    if (!playing || last == null) return;
    final dt = (elapsed - last).inMicroseconds / 1e6;
    var t = time.value + dt * speed;
    if (t >= duration) {
      if (loop) {
        t = 0;
      } else {
        t = duration;
        _setPlaying(false);
      }
    }
    time.value = t;
  }

  void _setPlaying(bool p) {
    if (playing == p) return;
    playing = p;
    notifyListeners();
  }

  void play() {
    if (time.value >= duration - 1e-3) seek(0);
    _setPlaying(true);
    _video?.play().toDart.catchError((_) => null);
  }

  void pause() {
    _setPlaying(false);
    _video?.pause();
  }

  void toggle() => playing ? pause() : play();

  void seek(double t) {
    final c = t.clamp(0.0, duration).toDouble();
    time.value = c;
    final v = _video;
    if (v != null) {
      if (v.readyState >= 1) {
        v.currentTime = c;
      } else {
        _pendingSeek = c;
      }
    }
  }

  void setSpeed(double s) {
    speed = s;
    _video?.playbackRate = s;
    notifyListeners();
  }

  void setLoop(bool l) {
    loop = l;
    notifyListeners();
  }

  /// Frame index of the camera at the current time.
  int get frame => (time.value * fps + 1e-6).floor();

  /// One frame forward / back: camera frames, or the LiDAR frames in LiDAR-only mode.
  void step(int dir) {
    pause();
    final st = stepTimes;
    if (st != null && st.isNotEmpty) {
      final t = time.value;
      if (dir > 0) {
        final next = st.firstWhere((x) => x > t + 1e-3, orElse: () => st.last);
        seek(next);
      } else {
        final prev = st.lastWhere((x) => x < t - 1e-3, orElse: () => st.first);
        seek(prev);
      }
      return;
    }
    final f = (frame + dir).clamp(0, (duration * fps).floor());
    seek((f + 0.5) / fps); // middle of the frame: no rounding at frame boundaries
  }

  void jump(double seconds) => seek(time.value + seconds);

  @override
  void dispose() {
    _video?.pause();
    time.dispose();
    super.dispose();
  }
}
