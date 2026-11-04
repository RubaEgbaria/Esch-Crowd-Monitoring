import 'package:material_ui/material_ui.dart';

import '../theme.dart';
import 'playback.dart';

const speeds = [0.25, 0.5, 1.0, 1.5, 2.0];

/// Play/pause, frame step, ±1 s, scrubber, speed, loop and the current time.
class PlayerBar extends StatelessWidget {
  const PlayerBar({super.key, required this.playback});
  final PlaybackController playback;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return ListenableBuilder(
      listenable: playback,
      builder: (context, _) {
        final p = playback;
        return Container(
          padding: const EdgeInsets.fromLTRB(8, 4, 12, 4),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: AppColors.border),
          ),
          child: Row(children: [
            _btn(Icons.replay, 'Back 1 s (Shift + ←)', () => p.jump(-1)),
            _btn(Icons.skip_previous_rounded, 'Previous frame (←)', () => p.step(-1)),
            IconButton.filled(
              tooltip: p.playing ? 'Pause (space)' : 'Play (space)',
              onPressed: p.toggle,
              icon: Icon(p.playing ? Icons.pause_rounded : Icons.play_arrow_rounded),
            ),
            _btn(Icons.skip_next_rounded, 'Next frame (→)', () => p.step(1)),
            _btn(Icons.forward, 'Forward 1 s (Shift + →)', () => p.jump(1)),
            const SizedBox(width: 6),
            ValueListenableBuilder<double>(
              valueListenable: p.time,
              builder: (_, now, _) => SizedBox(
                width: 118,
                child: Text('${now.toStringAsFixed(2)} / ${p.duration.toStringAsFixed(2)} s',
                    style: t.bodySmall?.copyWith(
                        color: AppColors.text, fontFeatures: const [FontFeature.tabularFigures()])),
              ),
            ),
            Expanded(
              child: ValueListenableBuilder<double>(
                valueListenable: p.time,
                builder: (_, now, _) => SliderTheme(
                  data: SliderTheme.of(context).copyWith(
                    trackHeight: 4,
                    thumbShape: const RoundSliderThumbShape(enabledThumbRadius: 7),
                    overlayShape: const RoundSliderOverlayShape(overlayRadius: 14),
                  ),
                  child: Slider(
                    value: now.clamp(0, p.duration),
                    max: p.duration,
                    onChanged: p.seek,
                  ),
                ),
              ),
            ),
            PopupMenuButton<double>(
              tooltip: 'Playback speed',
              initialValue: p.speed,
              onSelected: p.setSpeed,
              itemBuilder: (_) => [for (final s in speeds) PopupMenuItem(value: s, child: Text('${s}x'))],
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                decoration: BoxDecoration(
                  border: Border.all(color: AppColors.border),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text('${p.speed}x', style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
              ),
            ),
            const SizedBox(width: 4),
            IconButton(
              tooltip: p.loop ? 'Loop on' : 'Loop off',
              onPressed: () => p.setLoop(!p.loop),
              isSelected: p.loop,
              color: p.loop ? AppColors.primary : AppColors.textSecondary,
              icon: const Icon(Icons.repeat_rounded),
            ),
          ]),
        );
      },
    );
  }

  Widget _btn(IconData icon, String tip, VoidCallback onTap) =>
      IconButton(tooltip: tip, onPressed: onTap, icon: Icon(icon, size: 22), color: AppColors.text);
}
