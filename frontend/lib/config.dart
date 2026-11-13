/// Backend base URL, set with `--dart-define=BACKEND_URL=...`.
/// `same-origin` (hosted build): the API is served by the same server as this app.
const String _backendDefine = String.fromEnvironment(
  'BACKEND_URL',
  defaultValue: 'http://localhost:8000',
);

final String backendUrl = _backendDefine == 'same-origin' ? Uri.base.origin : _backendDefine;

const String appTitle = 'Crowd Monitoring: LiDAR + Camera Fusion';
const String appSubtitle = 'AE3S Lab, University of Luxembourg';
