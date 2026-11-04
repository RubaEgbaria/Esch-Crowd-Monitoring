import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/models.dart';
import '../../state/new_run.dart';
import '../../state/providers.dart';
import '../../theme.dart';
import '../../widgets/common.dart';
import '../../widgets/synced_text_field.dart';

class GroundTruthCard extends ConsumerWidget {
  const GroundTruthCard({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final st = ref.watch(newRunProvider);
    final ctl = ref.read(newRunProvider.notifier);
    final presets = ref.watch(presetsProvider).value?.groundTruth ?? const <GtPreset>[];
    final t = Theme.of(context).textTheme;

    GtPreset? byKey(String? k) {
      for (final p in presets) {
        if (p.key == k) return p;
      }
      return null;
    }

    final current = byKey(st.gtPreset);
    // Folder named like a preset (e.g. ".../baseline"): offer it.
    final folder = st.source == SourceKind.drive ? st.listing?.folderName.toLowerCase() : null;
    final suggested = byKey(folder);
    final showSuggestion = suggested != null && (!st.gtEnabled || st.gtPreset != suggested.key);

    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        CardTitle(
          'Ground truth',
          icon: Icons.flag_outlined,
          subtitle: 'Optional. People counts per time segment, as in your notebooks. '
              'Without it, the metrics and the learned fusion methods are hidden.',
          trailing: Switch(
            value: st.gtEnabled,
            onChanged: (v) => ctl.setGtEnabled(v, defaultPreset: suggested ?? (presets.isEmpty ? null : presets.first)),
          ),
        ),
        if (showSuggestion) ...[
          const SizedBox(height: 14),
          Notice(
            'This folder is named "${st.listing!.folderName}". Use the ${suggested.label} preset?',
            action: TextButton(onPressed: () => ctl.applyPreset(suggested), child: const Text('Use preset')),
          ),
        ],
        if (st.gtEnabled) ...[
          const SizedBox(height: 16),
          Text('Preset', style: t.labelLarge?.copyWith(color: AppColors.textSecondary)),
          const SizedBox(height: 8),
          Wrap(spacing: 8, runSpacing: 8, children: [
            for (final p in presets)
              ChoiceChip(
                label: Text(p.label),
                selected: st.gtPreset == p.key,
                onSelected: (_) => ctl.applyPreset(p),
              ),
            ChoiceChip(
              label: const Text('Custom'),
              selected: st.gtPreset == null,
              onSelected: (_) => ctl.setCustom(),
            ),
          ]),
          if (current != null) ...[
            const SizedBox(height: 8),
            Text('${current.description} · from ${current.source}', style: t.bodySmall),
          ],
          const SizedBox(height: 16),
          _SegmentsTable(st.segments),
          const SizedBox(height: 8),
          Row(children: [
            TextButton.icon(
              onPressed: ctl.addSegment,
              icon: const Icon(Icons.add, size: 18),
              label: const Text('Add segment'),
            ),
          ]),
          const SizedBox(height: 4),
          Text(
            'Times are seconds of video time. Use T for the end of the video and T-x for '
            'x seconds before the end. Times not covered by any segment count as 0 people (notebook rule).',
            style: t.bodySmall,
          ),
        ],
      ]),
    );
  }
}

class _SegmentsTable extends ConsumerWidget {
  const _SegmentsTable(this.segments);
  final List<SegmentDraft> segments;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ctl = ref.read(newRunProvider.notifier);
    final head = Theme.of(context).textTheme.bodySmall?.copyWith(fontWeight: FontWeight.w600);
    if (segments.isEmpty) {
      return Text('No segments. Choose a preset or add a segment.', style: Theme.of(context).textTheme.bodySmall);
    }
    return Column(children: [
      Row(children: [
        const SizedBox(width: 26),
        Expanded(child: Text('Start (s)', style: head)),
        const SizedBox(width: 8),
        Expanded(child: Text('End (s)', style: head)),
        const SizedBox(width: 8),
        SizedBox(width: 84, child: Text('People', style: head)),
        const SizedBox(width: 40),
      ]),
      const SizedBox(height: 6),
      for (var i = 0; i < segments.length; i++)
        Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            SizedBox(
              width: 26,
              child: Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Text('${i + 1}', style: Theme.of(context).textTheme.bodySmall),
              ),
            ),
            Expanded(
              child: SyncedTextField(
                value: segments[i].start,
                onChanged: (v) => ctl.editSegment(i, start: v),
                decoration: InputDecoration(errorText: SegmentDraft.tokenError(segments[i].start)),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: SyncedTextField(
                value: segments[i].end,
                onChanged: (v) => ctl.editSegment(i, end: v),
                decoration: InputDecoration(errorText: SegmentDraft.tokenError(segments[i].end)),
              ),
            ),
            const SizedBox(width: 8),
            SizedBox(
              width: 84,
              child: SyncedTextField(
                value: segments[i].people,
                keyboardType: TextInputType.number,
                onChanged: (v) => ctl.editSegment(i, people: v),
                decoration: InputDecoration(errorText: SegmentDraft.peopleError(segments[i].people)),
              ),
            ),
            SizedBox(
              width: 40,
              child: IconButton(
                tooltip: 'Remove segment',
                onPressed: () => ctl.removeSegment(i),
                icon: const Icon(Icons.close, size: 18, color: AppColors.textSecondary),
              ),
            ),
          ]),
        ),
    ]);
  }
}
