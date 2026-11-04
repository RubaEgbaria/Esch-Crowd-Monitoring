/// Backend base URL, set with `--dart-define=BACKEND_URL=...`.
const String backendUrl = String.fromEnvironment(
  'BACKEND_URL',
  defaultValue: 'http://localhost:8000',
);

const String appTitle = 'Crowd Monitoring: LiDAR + Camera Fusion';
const String appSubtitle = 'AE3S Lab, University of Luxembourg';
