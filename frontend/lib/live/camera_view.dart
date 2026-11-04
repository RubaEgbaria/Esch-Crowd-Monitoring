import 'dart:js_interop';

import 'package:flutter/foundation.dart';
import 'package:material_ui/material_ui.dart';
import 'package:web/web.dart' as web;

import '../theme.dart';
import 'live_models.dart';
import 'playback.dart';

/// The camera video (H.264 copy) with the notebook-style overlays drawn on top:
/// YOLO boxes with their confidence, the ROI of the floor homography, the GT phase label.
class CameraView extends StatefulWidget {
  const CameraView({
    super.key,
    required this.url,
    required this.playback,
    required this.result,
    required this.yolo,
    required this.conf,
    required this.showBoxes,
    required this.roi,
    required this.showRoi,
    this.hud,
  });

  final String url;
  final PlaybackController playback;
  final ModeResult result;
  final YoloData? yolo;
  final double conf;
  final bool showBoxes;
  final List<Offset>? roi;
  final bool showRoi;
  final Widget? hud;

  @override
  State<CameraView> createState() => _CameraViewState();
}

class _CameraViewState extends State<CameraView> {
  web.HTMLVideoElement? _video;
  bool _error = false;

  @override
  void dispose() {
    final v = _video;
    if (v != null) widget.playback.detachVideo(v);
    super.dispose();
  }

  void _created(Object el) {
    final v = el as web.HTMLVideoElement;
    v
      ..src = widget.url
      ..muted = true
      ..preload = 'auto'
      ..playsInline = true
      ..crossOrigin = 'anonymous';
    v.style
      ..width = '100%'
      ..height = '100%'
      ..objectFit = 'fill'
      ..pointerEvents = 'none'
      ..backgroundColor = '#0B1220';
    v.addEventListener('error', ((web.Event _) {
      if (mounted) setState(() => _error = true);
    }).toJS);
    _video = v;
    widget.playback.attachVideo(v);
  }

  @override
  Widget build(BuildContext context) {
    final r = widget.result;
    return AspectRatio(
      aspectRatio: r.width / r.height,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(10),
        child: Stack(fit: StackFit.expand, children: [
          const ColoredBox(color: Color(0xFF0B1220)),
          HtmlElementView.fromTagName(key: ValueKey(widget.url), tagName: 'video', onElementCreated: _created),
          IgnorePointer(
            child: CustomPaint(
              painter: _CameraOverlay(
                time: widget.playback.time,
                fps: r.fps,
                videoW: r.width,
                videoH: r.height,
                yolo: widget.showBoxes ? widget.yolo : null,
                conf: widget.conf,
                roi: widget.showRoi ? widget.roi : null,
                gtSegments: r.gtSegments,
              ),
            ),
          ),
          if (_error)
            const Center(
              child: Text('The camera video could not be loaded. Run Camera or Fusion to prepare it.',
                  style: TextStyle(color: Colors.white)),
            ),
          if (widget.hud != null) Positioned(left: 12, bottom: 12, child: widget.hud!),
        ]),
      ),
    );
  }
}

class _CameraOverlay extends CustomPainter {
  _CameraOverlay({
    required this.time,
    required this.fps,
    required this.videoW,
    required this.videoH,
    required this.yolo,
    required this.conf,
    required this.roi,
    required this.gtSegments,
  }) : super(repaint: time);

  final ValueListenable<double> time;
  final double fps, videoW, videoH, conf;
  final YoloData? yolo;
  final List<Offset>? roi;
  final List<List<num>>? gtSegments;

  static const roiColor = Color(0xFFF5C542);

  @override
  void paint(Canvas canvas, Size size) {
    final s = size.width / videoW;
    final t = time.value;

    // ROI of the floor homography (sensors_fusion cell 7) — draw_roi
    final roi = this.roi;
    if (roi != null && roi.length >= 3) {
      final path = Path()..moveTo(roi[0].dx * s, roi[0].dy * s);
      for (final p in roi.skip(1)) {
        path.lineTo(p.dx * s, p.dy * s);
      }
      path.close();
      canvas.drawPath(path, Paint()
        ..color = roiColor
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2);
      final top = roi.reduce((a, b) => a.dy < b.dy ? a : b);
      _label(canvas, 'ROI · approximate calibration', Offset(top.dx * s, top.dy * s - 22),
          bg: const Color(0xCC0B1220), fg: roiColor, size: 11);
    }

    // YOLO person boxes with their confidence — draw_yolo_boxes
    final y = yolo;
    if (y != null) {
      final frame = (t * fps + 1e-6).floor();
      final paint = Paint()
        ..color = AppColors.yolo
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2.2;
      for (final Float64List b in y.boxesAt(frame, conf)) {
        final rect = Rect.fromLTRB(b[0] * s, b[1] * s, b[2] * s, b[3] * s);
        canvas.drawRect(rect, paint);
        // above the box, or inside it when the box touches the top edge
        _label(canvas, b[4].toStringAsFixed(2), Offset(rect.left, rect.top >= 18 ? rect.top - 18 : rect.top + 2),
            bg: AppColors.yolo, fg: Colors.white, size: 11);
      }
    }

    // GT phase label, top centre — draw_phase_label
    final phase = gtPhaseAt(gtSegments, t);
    if (phase != null) {
      final txt = 'GT phase: ${phase[2]} people  (${phase[0].toStringAsFixed(1)}–${phase[1].toStringAsFixed(1)} s)';
      final tp = _tp(txt, Colors.white, 13, FontWeight.w600);
      final w = tp.width + 20;
      final rect = RRect.fromRectAndRadius(Rect.fromLTWH(size.width / 2 - w / 2, 12, w, tp.height + 10),
          const Radius.circular(6));
      canvas.drawRRect(rect, Paint()..color = const Color(0xE6000000));
      tp.paint(canvas, Offset(size.width / 2 - tp.width / 2, 17));
    }
  }

  static TextPainter _tp(String text, Color color, double size, FontWeight weight) => TextPainter(
        text: TextSpan(text: text, style: TextStyle(color: color, fontSize: size, fontWeight: weight, height: 1.1)),
        textDirection: TextDirection.ltr,
      )..layout();

  static void _label(Canvas canvas, String text, Offset at,
      {required Color bg, required Color fg, double size = 11}) {
    final tp = _tp(text, fg, size, FontWeight.w600);
    final r = RRect.fromRectAndRadius(Rect.fromLTWH(at.dx, at.dy, tp.width + 8, tp.height + 4), const Radius.circular(3));
    canvas.drawRRect(r, Paint()..color = bg);
    tp.paint(canvas, Offset(at.dx + 4, at.dy + 2));
  }

  @override
  bool shouldRepaint(_CameraOverlay old) =>
      old.yolo != yolo || old.conf != conf || old.roi != roi || old.gtSegments != gtSegments;
}
