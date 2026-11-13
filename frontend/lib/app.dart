import 'package:material_ui/material_ui.dart';
import 'package:go_router/go_router.dart';

import 'config.dart';
import 'live/live_models.dart';
import 'live/live_screen.dart';
import 'screens/new_run/new_run_screen.dart';
import 'screens/run_detail_screen.dart';
import 'screens/runs_screen.dart';
import 'theme.dart';

final _router = GoRouter(
  routes: [
    GoRoute(path: '/', builder: (_, _) => const RunsScreen()),
    GoRoute(path: '/new', builder: (_, _) => const NewRunScreen()),
    GoRoute(path: '/runs/:id', builder: (_, s) => RunDetailScreen(runId: s.pathParameters['id']!)),
    GoRoute(
      path: '/runs/:id/live',
      builder: (_, s) => LiveScreen(
        runId: s.pathParameters['id']!,
        initialMode: LiveModeX.parse(s.uri.queryParameters['mode']),
        initialTime: double.tryParse(s.uri.queryParameters['t'] ?? ''),
        openParams: s.uri.queryParameters['panel'] == 'params',
      ),
    ),
  ],
);

class CrowdApp extends StatelessWidget {
  const CrowdApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp.router(
      title: appTitle,
      debugShowCheckedModeBanner: false,
      theme: buildTheme(),
      themeMode: ThemeMode.light,
      routerConfig: _router,
    );
  }
}
