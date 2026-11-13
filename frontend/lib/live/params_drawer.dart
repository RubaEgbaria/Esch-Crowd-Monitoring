import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import '../theme.dart';
import '../widgets/synced_text_field.dart';
import 'live_controller.dart';
import 'live_models.dart';

const amber = Color(0xFFB45309);
const amberBg = Color(0xFFFFFBEB);
const amberBorder = Color(0xFFFCD34D);
const bestColor = Color(0xFF0F9D8F);

/// Side drawer with every LiDAR / YOLO / Sync parameter. Always editable.
/// LiDAR changes do not rerun anything: the Run button is enabled instead.
class ParamsDrawer extends ConsumerWidget {
  const ParamsDrawer({super.key, required this.runId});
  final String runId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final st = ref.watch(liveProvider(runId));
    final ctl = ref.read(liveProvider(runId).notifier);
    final t = Theme.of(context).textTheme;
    final groups = <String, List<ParamSpec>>{};
    for (final s in st.schema) {
      (groups[s.group] ??= []).add(s);
    }
    final needsRun = st.available(st.mode) && !st.cached(st.mode);
    return Drawer(
      width: 460,
      backgroundColor: AppColors.page,
      shape: const RoundedRectangleBorder(),
      child: SafeArea(
        child: Column(children: [
          Container(
            color: Colors.white,
            padding: const EdgeInsets.fromLTRB(20, 16, 8, 12),
            child: Row(children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('Parameters', style: t.titleLarge),
                  Text('Best = the notebook defaults (eps 0.10 won the eps sweep)', style: t.bodySmall),
                ]),
              ),
              TextButton(
                onPressed: st.nonBest > 0 ? () => ctl.resetAll() : null,
                child: Text(st.nonBest > 0 ? 'Reset all to best (${st.nonBest})' : 'All at best'),
              ),
              IconButton(onPressed: () => Navigator.of(context).maybePop(), icon: const Icon(Icons.close)),
            ]),
          ),
          const Divider(),
          if (needsRun)
            Container(
              width: double.infinity,
              color: amberBg,
              padding: const EdgeInsets.fromLTRB(20, 10, 12, 10),
              child: Row(children: [
                const Icon(Icons.info_outline, color: amber, size: 18),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    st.results[st.mode] == null
                        ? '${st.mode.short} has not been run with these parameters.'
                        : 'Parameters changed, run again.',
                    style: const TextStyle(color: amber, fontWeight: FontWeight.w600),
                  ),
                ),
                FilledButton(
                  onPressed: st.busy ? null : ctl.run,
                  child: Text('Run ${st.mode.short}'),
                ),
              ]),
            ),
          Expanded(
            child: ListView(padding: const EdgeInsets.fromLTRB(12, 12, 12, 24), children: [
              for (final e in groups.entries)
                _Group(
                  title: e.key,
                  specs: e.value,
                  params: st.params,
                  subtitle: switch (e.key) {
                    'LiDAR' => 'Applied when you run LiDAR only or Fusion again.',
                    'YOLO' => 'Filters the stored boxes instantly; Fusion is refit when you run it again.',
                    _ => 'How the LiDAR is placed on the video timeline.',
                  },
                  onChanged: ctl.setParam,
                  onReset: ctl.resetParam,
                  onResetGroup: () => ctl.resetAll(group: e.key),
                ),
            ]),
          ),
        ]),
      ),
    );
  }
}

class _Group extends StatelessWidget {
  const _Group({
    required this.title,
    required this.subtitle,
    required this.specs,
    required this.params,
    required this.onChanged,
    required this.onReset,
    required this.onResetGroup,
  });
  final String title;
  final String subtitle;
  final List<ParamSpec> specs;
  final Map<String, dynamic> params;
  final void Function(String, Object?) onChanged;
  final void Function(String) onReset;
  final VoidCallback onResetGroup;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final changed = specs.where((s) => !s.equalsBest(params[s.key])).length;
    final sections = <String, List<ParamSpec>>{};
    for (final s in specs) {
      (sections[s.section] ??= []).add(s);
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Material(
        color: Colors.white,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(kRadius),
          side: const BorderSide(color: AppColors.border),
        ),
        clipBehavior: Clip.antiAlias,
        child: Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          initiallyExpanded: true,
          shape: const RoundedRectangleBorder(),
          expandedCrossAxisAlignment: CrossAxisAlignment.stretch,
          title: Row(children: [
            Text(title, style: t.titleMedium),
            const SizedBox(width: 8),
            if (changed > 0)
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
                decoration: BoxDecoration(color: amberBg, borderRadius: BorderRadius.circular(99),
                    border: Border.all(color: amberBorder)),
                child: Text('$changed changed', style: const TextStyle(color: amber, fontSize: 11.5, fontWeight: FontWeight.w600)),
              ),
          ]),
          subtitle: Text(subtitle, style: t.bodySmall),
          childrenPadding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
          children: [
            if (changed > 0)
              Align(
                alignment: Alignment.centerRight,
                child: TextButton.icon(
                  onPressed: onResetGroup,
                  icon: const Icon(Icons.restart_alt, size: 16),
                  label: Text('Reset $title to best'),
                ),
              ),
            for (final sec in sections.entries) ...[
              if (sections.length > 1)
                Padding(
                  padding: const EdgeInsets.fromLTRB(4, 10, 4, 4),
                  child: Text(sec.key.toUpperCase(),
                      style: t.bodySmall?.copyWith(fontWeight: FontWeight.w700, letterSpacing: 0.5)),
                ),
              for (final s in sec.value)
                ParamRow(spec: s, value: params[s.key], onChanged: (v) => onChanged(s.key, v), onReset: () => onReset(s.key)),
            ],
          ],
        ),
        ),
      ),
    );
  }
}

String fmtValue(ParamSpec s, Object? v) {
  if (v == null) return 'auto';
  if (v is List) return '${fmtValue(s, v[0])}–${fmtValue(s, v[1])}';
  if (v is bool) return v ? 'on' : 'off';
  final n = (v as num).toDouble();
  return s.kind == 'int' ? n.round().toString() : n.toStringAsFixed(s.decimals);
}

/// One parameter: label + tooltip + Best badge, slider with the best tick, number input.
class ParamRow extends StatelessWidget {
  const ParamRow({super.key, required this.spec, required this.value, required this.onChanged, required this.onReset});
  final ParamSpec spec;
  final Object? value;
  final ValueChanged<Object?> onChanged;
  final VoidCallback onReset;

  double _snap(double v) {
    final s = spec.step;
    final snapped = (v / s).round() * s;
    return double.parse(snapped.clamp(spec.min, spec.max).toStringAsFixed(spec.kind == 'int' ? 0 : spec.decimals));
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final atBest = spec.equalsBest(value);
    return Container(
      margin: const EdgeInsets.only(top: 6),
      padding: const EdgeInsets.fromLTRB(10, 8, 6, 6),
      decoration: BoxDecoration(
        color: atBest ? Colors.white : amberBg,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: atBest ? Colors.transparent : amberBorder),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Flexible(
            child: Text(spec.label,
                style: t.bodyMedium?.copyWith(fontWeight: FontWeight.w600, color: atBest ? AppColors.text : amber)),
          ),
          if (spec.unit.isNotEmpty) Text(' (${spec.unit})', style: t.bodySmall),
          const SizedBox(width: 4),
          Tooltip(
            message: spec.help,
            preferBelow: false,
            child: const Icon(Icons.help_outline, size: 15, color: AppColors.textSecondary),
          ),
          const SizedBox(width: 8),
          _BestBadge(text: 'Best ${fmtValue(spec, spec.best)}', active: atBest),
          const Spacer(),
          if (!atBest)
            TextButton(
              style: TextButton.styleFrom(foregroundColor: amber, padding: const EdgeInsets.symmetric(horizontal: 8),
                  minimumSize: const Size(0, 30)),
              onPressed: onReset,
              child: const Text('Reset to best', style: TextStyle(fontSize: 12.5)),
            ),
        ]),
        _control(context, atBest),
      ]),
    );
  }

  Widget _control(BuildContext context, bool atBest) {
    switch (spec.kind) {
      case 'bool':
        return Row(children: [
          Switch(value: value == true, onChanged: (v) => onChanged(v)),
          const SizedBox(width: 8),
          Text(value == true ? 'On' : 'Off', style: Theme.of(context).textTheme.bodySmall),
        ]);
      case 'range':
        final lo = ((value as List)[0] as num).toDouble(), hi = (value as List)[1] as num;
        final best = spec.best as List;
        return Row(children: [
          Expanded(
            child: SliderTheme(
              data: SliderTheme.of(context).copyWith(
                rangeTrackShape: _BestTickRangeTrack([
                  _frac((best[0] as num).toDouble()),
                  _frac((best[1] as num).toDouble()),
                ]),
              ),
              child: RangeSlider(
                values: RangeValues(lo.clamp(spec.min, spec.max), hi.toDouble().clamp(spec.min, spec.max)),
                min: spec.min,
                max: spec.max,
                onChanged: (r) {
                  final a = _snap(r.start), b = _snap(r.end);
                  if (a < b) onChanged([a, b]);
                },
              ),
            ),
          ),
          _NumberBox(spec: spec, value: lo, onSubmit: (v) {
            if (v < hi) onChanged([_snap(v), hi.toDouble()]);
          }),
          const Padding(padding: EdgeInsets.symmetric(horizontal: 4), child: Text('–')),
          _NumberBox(spec: spec, value: hi.toDouble(), onSubmit: (v) {
            if (v > lo) onChanged([lo, _snap(v)]);
          }),
        ]);
      case 'offset':
        final manual = value != null;
        final v = manual ? (value as num).toDouble() : 0.0;
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SegmentedButton<bool>(
            showSelectedIcon: false,
            segments: const [
              ButtonSegment(value: false, label: Text('Auto (cross-correlation)')),
              ButtonSegment(value: true, label: Text('Manual')),
            ],
            selected: {manual},
            onSelectionChanged: (s) => onChanged(s.first ? 0.0 : null),
          ),
          if (manual) _sliderRow(context, v, null),
        ]);
      default:
        return _sliderRow(context, (value as num? ?? 0).toDouble(), _frac((spec.best as num).toDouble()));
    }
  }

  double _frac(double v) => ((v - spec.min) / (spec.max - spec.min)).clamp(0.0, 1.0);

  Widget _sliderRow(BuildContext context, double v, double? bestFrac) {
    final divisions = ((spec.max - spec.min) / spec.step).round();
    return Row(children: [
      Expanded(
        child: SliderTheme(
          data: SliderTheme.of(context).copyWith(
            trackShape: _BestTickTrack(bestFrac),
            tickMarkShape: SliderTickMarkShape.noTickMark,
          ),
          child: Slider(
            value: v.clamp(spec.min, spec.max),
            min: spec.min,
            max: spec.max,
            divisions: divisions > 0 && divisions <= 400 ? divisions : null,
            onChanged: (x) => onChanged(spec.kind == 'int' ? _snap(x).round() : _snap(x)),
          ),
        ),
      ),
      _NumberBox(spec: spec, value: v, onSubmit: (x) => onChanged(spec.kind == 'int' ? _snap(x).round() : _snap(x))),
    ]);
  }
}

class _BestBadge extends StatelessWidget {
  const _BestBadge({required this.text, required this.active});
  final String text;
  final bool active;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
        decoration: BoxDecoration(
          color: active ? bestColor : Colors.white,
          borderRadius: BorderRadius.circular(99),
          border: Border.all(color: bestColor),
        ),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          if (active) const Icon(Icons.check, size: 11, color: Colors.white),
          if (active) const SizedBox(width: 2),
          Text(text, style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w700, color: active ? Colors.white : bestColor)),
        ]),
      );
}

class _NumberBox extends StatelessWidget {
  const _NumberBox({required this.spec, required this.value, required this.onSubmit});
  final ParamSpec spec;
  final double value;
  final ValueChanged<double> onSubmit;

  @override
  Widget build(BuildContext context) {
    final text = spec.kind == 'int' ? value.round().toString() : value.toStringAsFixed(spec.decimals);
    void submit(String s) {
      final v = double.tryParse(s.replaceAll(',', '.'));
      if (v != null && v >= spec.min && v <= spec.max) onSubmit(v);
    }

    return SizedBox(
      width: 64,
      child: Tooltip(
        message: 'Type a value and press Enter (${spec.min}–${spec.max})',
        waitDuration: const Duration(milliseconds: 800),
        child: SyncedTextField(
          value: text,
          onChanged: (_) {},
          onSubmitted: submit,
          textAlign: TextAlign.right,
          keyboardType: const TextInputType.numberWithOptions(decimal: true, signed: true),
          style: const TextStyle(fontSize: 13, fontFeatures: [FontFeature.tabularFigures()]),
          decoration: const InputDecoration(contentPadding: EdgeInsets.symmetric(horizontal: 8, vertical: 8)),
        ),
      ),
    );
  }
}

/// Slider track with a coloured tick at the best value.
class _BestTickTrack extends RoundedRectSliderTrackShape {
  const _BestTickTrack(this.bestFrac);
  final double? bestFrac;

  @override
  void paint(
    PaintingContext context,
    Offset offset, {
    required RenderBox parentBox,
    required SliderThemeData sliderTheme,
    required Animation<double> enableAnimation,
    required TextDirection textDirection,
    required Offset thumbCenter,
    Offset? secondaryOffset,
    bool isDiscrete = false,
    bool isEnabled = false,
    double additionalActiveTrackHeight = 2,
  }) {
    super.paint(context, offset,
        parentBox: parentBox,
        sliderTheme: sliderTheme,
        enableAnimation: enableAnimation,
        textDirection: textDirection,
        thumbCenter: thumbCenter,
        secondaryOffset: secondaryOffset,
        isDiscrete: isDiscrete,
        isEnabled: isEnabled,
        additionalActiveTrackHeight: additionalActiveTrackHeight);
    final f = bestFrac;
    if (f == null) return;
    final rect = getPreferredRect(parentBox: parentBox, offset: offset, sliderTheme: sliderTheme,
        isEnabled: isEnabled, isDiscrete: isDiscrete);
    _tick(context.canvas, rect, f);
  }
}

class _BestTickRangeTrack extends RoundedRectRangeSliderTrackShape {
  const _BestTickRangeTrack(this.fracs);
  final List<double> fracs;

  @override
  void paint(
    PaintingContext context,
    Offset offset, {
    required RenderBox parentBox,
    required SliderThemeData sliderTheme,
    required Animation<double> enableAnimation,
    required Offset startThumbCenter,
    required Offset endThumbCenter,
    bool isEnabled = false,
    bool isDiscrete = false,
    required TextDirection textDirection,
    double additionalActiveTrackHeight = 2,
  }) {
    super.paint(context, offset,
        parentBox: parentBox,
        sliderTheme: sliderTheme,
        enableAnimation: enableAnimation,
        startThumbCenter: startThumbCenter,
        endThumbCenter: endThumbCenter,
        isEnabled: isEnabled,
        isDiscrete: isDiscrete,
        textDirection: textDirection,
        additionalActiveTrackHeight: additionalActiveTrackHeight);
    final rect = getPreferredRect(parentBox: parentBox, offset: offset, sliderTheme: sliderTheme,
        isEnabled: isEnabled, isDiscrete: isDiscrete);
    for (final f in fracs) {
      _tick(context.canvas, rect, f);
    }
  }
}

void _tick(Canvas canvas, Rect track, double f) {
  final x = track.left + track.width * f;
  canvas.drawRRect(
    RRect.fromRectAndRadius(Rect.fromCenter(center: Offset(x, track.center.dy), width: 3, height: track.height + 12),
        const Radius.circular(1.5)),
    Paint()..color = bestColor,
  );
}
