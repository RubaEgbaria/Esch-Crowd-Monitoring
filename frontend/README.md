# Frontend (Flutter web)

The web UI of the Crowd Monitoring app. See the [main README](../README.md) for setup and how to run it.

```
flutter pub get
flutter run -d chrome --dart-define=BACKEND_URL=http://localhost:8000
```

Material widgets come from `package:material_ui` (the Material library decoupled
from the Flutter SDK), because `go_router` and `google_fonts` are built on it.
