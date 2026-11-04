import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../api/api_client.dart';
import '../../api/models.dart';
import '../../state/new_run.dart';
import '../../state/providers.dart';
import '../../theme.dart';
import '../../util/format.dart';
import '../../util/web_files.dart';
import '../../widgets/common.dart';
import '../../widgets/synced_text_field.dart';

class SourceCard extends ConsumerStatefulWidget {
  const SourceCard({super.key});

  @override
  ConsumerState<SourceCard> createState() => _SourceCardState();
}

class _SourceCardState extends ConsumerState<SourceCard> with SingleTickerProviderStateMixin {
  late final TabController _tabs = TabController(
    length: 2,
    vsync: this,
    initialIndex: ref.read(newRunProvider).source == SourceKind.upload ? 1 : 0,
  );

  @override
  void initState() {
    super.initState();
    _tabs.addListener(() {
      if (!_tabs.indexIsChanging) {
        ref.read(newRunProvider.notifier).setSource(_tabs.index == 0 ? SourceKind.drive : SourceKind.upload);
      }
    });
  }

  @override
  void dispose() {
    _tabs.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final st = ref.watch(newRunProvider);
    final ctl = ref.read(newRunProvider.notifier);
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        const CardTitle('Recording', icon: Icons.sensors,
            subtitle: 'A Qb2 LiDAR recording (.zip) and a camera video of the same scene.'),
        const SizedBox(height: 18),
        SyncedTextField(
          value: st.name,
          onChanged: ctl.setName,
          decoration: const InputDecoration(labelText: 'Run name', hintText: 'e.g. baseline'),
        ),
        const SizedBox(height: 16),
        TabBar(
          controller: _tabs,
          isScrollable: true,
          tabAlignment: TabAlignment.start,
          tabs: const [
            Tab(icon: Icon(Icons.add_to_drive, size: 18), iconMargin: EdgeInsets.zero, height: 44, text: 'Google Drive'),
            Tab(icon: Icon(Icons.upload_file, size: 18), iconMargin: EdgeInsets.zero, height: 44, text: 'Upload files'),
          ],
        ),
        const SizedBox(height: 18),
        AnimatedSize(
          duration: const Duration(milliseconds: 150),
          alignment: Alignment.topCenter,
          child: st.source == SourceKind.drive ? const _DriveTab() : const _UploadTab(),
        ),
      ]),
    );
  }
}

// ====================================================================== Drive
class _DriveTab extends ConsumerWidget {
  const _DriveTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final drive = ref.watch(driveProvider);
    final st = ref.watch(newRunProvider);
    final ctl = ref.read(newRunProvider.notifier);
    final signedIn = drive.value?.signedIn ?? false;

    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      const _DriveAuth(),
      const SizedBox(height: 16),
      Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(
          child: SyncedTextField(
            value: st.driveQuery,
            enabled: signedIn && !st.resolving,
            onChanged: ctl.setDriveQuery,
            onSubmitted: (_) => ctl.resolve(),
            decoration: const InputDecoration(
              labelText: 'Folder link or path',
              hintText: 'My Drive/Crowd-Density-Monitoring/Code/baseline',
              helperText: 'A folder share link, or a path like DRIVE_ROOT in your notebooks. '
                  'The folder does not need to be public.',
              helperMaxLines: 2,
              prefixIcon: Icon(Icons.folder_outlined, size: 20),
            ),
          ),
        ),
        const SizedBox(width: 10),
        Padding(
          padding: const EdgeInsets.only(top: 1),
          child: FilledButton.tonalIcon(
            style: FilledButton.styleFrom(
              backgroundColor: AppColors.primaryTint,
              foregroundColor: AppColors.primary,
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 15),
            ),
            onPressed: signedIn && !st.resolving && st.driveQuery.trim().isNotEmpty ? ctl.resolve : null,
            icon: const Icon(Icons.search, size: 18),
            label: const Text('Find files'),
          ),
        ),
      ]),
      if (st.resolving) ...[
        const SizedBox(height: 14),
        const LinearProgressIndicator(minHeight: 3),
        const SizedBox(height: 6),
        Text('Looking up the folder on Google Drive…', style: Theme.of(context).textTheme.bodySmall),
      ],
      if (st.resolveError != null) ...[
        const SizedBox(height: 14),
        Notice(st.resolveError!, kind: NoticeKind.error),
      ],
      if (st.listing != null) ...[
        const SizedBox(height: 18),
        _DriveListingView(st),
      ],
    ]);
  }
}

class _DriveAuth extends ConsumerWidget {
  const _DriveAuth();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final drive = ref.watch(driveProvider);
    final t = Theme.of(context).textTheme;

    Future<void> signIn() async {
      try {
        await ref.read(driveProvider.notifier).signIn();
      } on ApiException catch (e) {
        if (context.mounted) showError(context, e);
      }
    }

    return drive.when(
      skipLoadingOnRefresh: true,
      loading: () => const LinearProgressIndicator(minHeight: 2),
      error: (e, _) => Notice(e.toString(), kind: NoticeKind.error,
          action: TextButton(onPressed: () => ref.invalidate(driveProvider), child: const Text('Retry'))),
      data: (st) {
        if (!st.clientConfigured) {
          return Notice(
            st.clientMessage,
            title: 'Google Drive is not set up yet',
            kind: NoticeKind.warning,
            action: TextButton(
                onPressed: () => ref.read(driveProvider.notifier).refresh(), child: const Text('Check again')),
          );
        }
        if (st.signedIn) {
          final who = st.displayName.isNotEmpty ? st.displayName : 'Google account';
          return Container(
            padding: const EdgeInsets.fromLTRB(12, 8, 8, 8),
            decoration: BoxDecoration(color: AppColors.page, borderRadius: BorderRadius.circular(8),
                border: Border.all(color: AppColors.border)),
            child: Row(children: [
              CircleAvatar(
                radius: 15,
                backgroundColor: AppColors.primary,
                child: Text(who.characters.first.toUpperCase(),
                    style: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w600)),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('Signed in as $who', style: t.bodyMedium?.copyWith(fontWeight: FontWeight.w600)),
                  if (st.email.isNotEmpty) Text('${st.email} · read-only access', style: t.bodySmall),
                ]),
              ),
              TextButton(onPressed: () => ref.read(driveProvider.notifier).signOut(), child: const Text('Sign out')),
            ]),
          );
        }
        if (st.signinState == 'pending') {
          return Notice(
            'Finish signing in in the Google tab that just opened. This page updates by itself.',
            title: 'Waiting for Google sign-in…',
            action: st.authUrl == null
                ? null
                : TextButton(
                    onPressed: () => launchUrl(Uri.parse(st.authUrl!), webOnlyWindowName: '_blank'),
                    child: const Text('Open the sign-in page'),
                  ),
          );
        }
        return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          if (st.signinError != null) ...[
            Notice(st.signinError!, kind: NoticeKind.error),
            const SizedBox(height: 10),
          ],
          Row(children: [
            Expanded(
              child: Text('Sign in with Google to read your Drive folders (read-only).',
                  style: t.bodyMedium?.copyWith(color: AppColors.textSecondary)),
            ),
            const SizedBox(width: 12),
            OutlinedButton.icon(
              onPressed: signIn,
              icon: const Icon(Icons.login, size: 18),
              label: const Text('Sign in with Google'),
            ),
          ]),
        ]);
      },
    );
  }
}

class _DriveListingView extends ConsumerWidget {
  const _DriveListingView(this.st);
  final NewRunState st;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = st.listing!;
    final ctl = ref.read(newRunProvider.notifier);
    final t = Theme.of(context).textTheme;
    final selectedIds = {for (final r in allRoles) st.selection[r]: r};

    return Container(
      decoration: BoxDecoration(border: Border.all(color: AppColors.border), borderRadius: BorderRadius.circular(10)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Container(
          padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
          decoration: const BoxDecoration(
            color: AppColors.page,
            borderRadius: BorderRadius.vertical(top: Radius.circular(10)),
          ),
          child: Row(children: [
            const Icon(Icons.folder, color: AppColors.primary, size: 20),
            const SizedBox(width: 10),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(l.folderName, style: t.titleSmall),
                Text(l.folderPath, style: t.bodySmall, maxLines: 1, overflow: TextOverflow.ellipsis),
              ]),
            ),
            Text('${l.files.length} files', style: t.bodySmall),
          ]),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(14, 14, 14, 6),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            for (final n in l.notes) ...[Notice(n, kind: NoticeKind.warning), const SizedBox(height: 10)],
            for (final role in allRoles) ...[
              _RolePicker(
                role: role,
                files: [for (final f in l.files) if (f.candidateRoles.contains(role)) f],
                selectedId: st.selection[role],
                onChanged: (id) => ctl.select(role, id),
              ),
              const SizedBox(height: 10),
            ],
          ]),
        ),
        const Divider(),
        Padding(
          padding: const EdgeInsets.fromLTRB(14, 10, 14, 4),
          child: Text('All files in the folder', style: t.bodySmall?.copyWith(fontWeight: FontWeight.w600)),
        ),
        for (final f in l.files)
          _ListingRow(
            icon: Icons.insert_drive_file_outlined,
            name: f.name,
            size: formatBytes(f.size),
            tag: selectedIds[f.id] == null ? null : roleShortLabels[selectedIds[f.id]],
          ),
        for (final name in l.subfolders)
          _ListingRow(icon: Icons.folder_outlined, name: '$name/', size: '', tag: null),
        Padding(
          padding: const EdgeInsets.fromLTRB(14, 8, 14, 12),
          child: Text(
            'Unselected files and subfolders (e.g. outputs/) are ignored. '
            'Selected files will be downloaded: ${formatBytes(st.downloadBytes)}.',
            style: t.bodySmall,
          ),
        ),
      ]),
    );
  }
}

class _RolePicker extends StatelessWidget {
  const _RolePicker({required this.role, required this.files, required this.selectedId, required this.onChanged});
  final String role;
  final List<DriveFile> files;
  final String? selectedId;
  final ValueChanged<String?> onChanged;

  @override
  Widget build(BuildContext context) {
    final required = requiredRoles.contains(role);
    final ids = files.map((f) => f.id).toSet();
    return InputDecorator(
      decoration: InputDecoration(
        labelText: '${roleLabels[role]}${required ? '' : ' (optional)'}',
        errorText: required && selectedId == null ? (files.isEmpty ? 'No matching file in this folder' : 'Required') : null,
        contentPadding: const EdgeInsets.fromLTRB(12, 4, 8, 4),
      ),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<String?>(
          isExpanded: true,
          value: ids.contains(selectedId) ? selectedId : null,
          hint: Text(required ? 'Select a file' : 'None'),
          items: [
            if (!required) const DropdownMenuItem<String?>(value: null, child: Text('None')),
            for (final f in files)
              DropdownMenuItem<String?>(
                value: f.id,
                child: Text('${f.name}   ·   ${formatBytes(f.size)}', overflow: TextOverflow.ellipsis),
              ),
          ],
          onChanged: onChanged,
        ),
      ),
    );
  }
}

class _ListingRow extends StatelessWidget {
  const _ListingRow({required this.icon, required this.name, required this.size, required this.tag});
  final IconData icon;
  final String name;
  final String size;
  final String? tag;

  @override
  Widget build(BuildContext context) {
    final used = tag != null;
    final style = TextStyle(fontSize: 13.5, color: used ? AppColors.text : AppColors.textSecondary,
        fontWeight: used ? FontWeight.w500 : FontWeight.w400);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 5),
      child: Row(children: [
        Icon(icon, size: 16, color: used ? AppColors.primary : const Color(0xFF9AA6B8)),
        const SizedBox(width: 10),
        Expanded(child: Text(name, style: style, overflow: TextOverflow.ellipsis)),
        if (tag != null) ...[
          Pill(tag!, color: AppColors.primary, background: AppColors.primaryTint),
          const SizedBox(width: 10),
        ] else
          const Padding(
            padding: EdgeInsets.only(right: 10),
            child: Text('ignored', style: TextStyle(fontSize: 12, color: Color(0xFF9AA6B8))),
          ),
        SizedBox(width: 72, child: Text(size, textAlign: TextAlign.right, style: style)),
      ]),
    );
  }
}

// ====================================================================== Upload
class _UploadTab extends ConsumerWidget {
  const _UploadTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final st = ref.watch(newRunProvider);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      for (final role in allRoles) ...[_UploadRow(role: role, file: st.uploads[role]), const SizedBox(height: 10)],
      Text(
        'Files are copied into data/runs/<run>/ on this laptop. The sensor UI recording is only shown '
        'as a reference video (it is not synchronised).',
        style: Theme.of(context).textTheme.bodySmall,
      ),
    ]);
  }
}

class _UploadRow extends ConsumerWidget {
  const _UploadRow({required this.role, required this.file});
  final String role;
  final PickedFile? file;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ctl = ref.read(newRunProvider.notifier);
    final t = Theme.of(context).textTheme;
    final required = requiredRoles.contains(role);
    final hint = switch (role) {
      roleLidarZip => 'e.g. 192.168.137.36_2026-09-08_11-33-52.zip',
      roleCameraVideo => 'e.g. raw-vid.mp4',
      _ => 'e.g. lidar_top_view.mp4',
    };
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 12, 10, 12),
      decoration: BoxDecoration(
        color: file == null ? AppColors.page : Colors.white,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: file == null ? AppColors.border : AppColors.primary.withValues(alpha: 0.35)),
      ),
      child: Row(children: [
        Icon(
          switch (role) {
            roleLidarZip => Icons.radar,
            roleCameraVideo => Icons.videocam_outlined,
            _ => Icons.ondemand_video_outlined,
          },
          color: role == roleLidarZip ? AppColors.lidar : AppColors.primary,
          size: 22,
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Text(roleLabels[role]!, style: t.bodyMedium?.copyWith(fontWeight: FontWeight.w600)),
              const SizedBox(width: 8),
              Pill(required ? 'Required' : 'Optional'),
            ]),
            const SizedBox(height: 2),
            Text(
              file == null ? hint : '${file!.name}  ·  ${formatBytes(file!.size)}',
              style: file == null ? t.bodySmall : t.bodyMedium,
              overflow: TextOverflow.ellipsis,
            ),
          ]),
        ),
        if (file != null)
          IconButton(
            tooltip: 'Remove',
            onPressed: () => ctl.clearUpload(role),
            icon: const Icon(Icons.close, size: 18, color: AppColors.textSecondary),
          ),
        OutlinedButton(
          onPressed: () => ctl.pick(role),
          child: Text(file == null ? 'Choose file' : 'Change'),
        ),
      ]),
    );
  }
}
