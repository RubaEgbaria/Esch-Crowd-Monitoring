import 'package:material_ui/material_ui.dart';
import 'package:google_fonts/google_fonts.dart';

/// Light theme only. Source colours are fixed and used everywhere
/// (counts, charts, boxes, legends).
class AppColors {
  static const background = Color(0xFFFFFFFF);
  static const page = Color(0xFFF7F9FC);
  static const card = Color(0xFFFFFFFF);
  static const border = Color(0xFFE3E8EF);
  static const text = Color(0xFF1B2A4A);
  static const textSecondary = Color(0xFF5B6B82);
  static const primary = Color(0xFF1E3A8A);
  static const primaryTint = Color(0xFFE8EEFB);
  static const neutralTint = Color(0xFFEEF2F7);
  static const error = Color(0xFFDC2626);
  static const errorTint = Color(0xFFFDECEC);

  // Sources
  static const lidar = Color(0xFF0F9D8F);
  static const yolo = Color(0xFF16A34A);
  static const fusion = Color(0xFF4F46E5);
  static const groundTruth = Color(0xFF1B2A4A);
}

const double kRadius = 12;

ThemeData buildTheme() {
  const scheme = ColorScheme(
    brightness: Brightness.light,
    primary: AppColors.primary,
    onPrimary: Colors.white,
    primaryContainer: AppColors.primaryTint,
    onPrimaryContainer: AppColors.primary,
    secondary: AppColors.primary,
    onSecondary: Colors.white,
    secondaryContainer: AppColors.primaryTint,
    onSecondaryContainer: AppColors.primary,
    surface: AppColors.card,
    onSurface: AppColors.text,
    onSurfaceVariant: AppColors.textSecondary,
    surfaceContainerLowest: AppColors.card,
    surfaceContainerLow: AppColors.page,
    surfaceContainer: AppColors.page,
    surfaceContainerHigh: AppColors.neutralTint,
    surfaceContainerHighest: AppColors.neutralTint,
    outline: AppColors.border,
    outlineVariant: AppColors.border,
    error: AppColors.error,
    onError: Colors.white,
    errorContainer: AppColors.errorTint,
    onErrorContainer: AppColors.error,
  );

  final base = ThemeData(colorScheme: scheme, useMaterial3: true);
  final text = GoogleFonts.interTextTheme(base.textTheme).apply(
    bodyColor: AppColors.text,
    displayColor: AppColors.text,
  );
  final radius = BorderRadius.circular(8);

  return base.copyWith(
    scaffoldBackgroundColor: AppColors.page,
    textTheme: text.copyWith(
      headlineSmall: text.headlineSmall?.copyWith(fontWeight: FontWeight.w700, fontSize: 24),
      titleLarge: text.titleLarge?.copyWith(fontWeight: FontWeight.w700, fontSize: 19),
      titleMedium: text.titleMedium?.copyWith(fontWeight: FontWeight.w600, fontSize: 15.5),
      titleSmall: text.titleSmall?.copyWith(fontWeight: FontWeight.w600),
      bodyMedium: text.bodyMedium?.copyWith(fontSize: 14, height: 1.45),
      bodySmall: text.bodySmall?.copyWith(color: AppColors.textSecondary, fontSize: 12.5, height: 1.4),
      labelLarge: text.labelLarge?.copyWith(fontWeight: FontWeight.w600),
    ),
    dividerTheme: const DividerThemeData(color: AppColors.border, thickness: 1, space: 1),
    cardTheme: CardThemeData(
      color: AppColors.card,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(kRadius),
        side: const BorderSide(color: AppColors.border),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      isDense: true,
      filled: true,
      fillColor: Colors.white,
      contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
      labelStyle: const TextStyle(color: AppColors.textSecondary),
      hintStyle: const TextStyle(color: Color(0xFF9AA6B8)),
      helperStyle: const TextStyle(color: AppColors.textSecondary, fontSize: 12),
      border: OutlineInputBorder(borderRadius: radius, borderSide: const BorderSide(color: AppColors.border)),
      enabledBorder: OutlineInputBorder(borderRadius: radius, borderSide: const BorderSide(color: AppColors.border)),
      focusedBorder: OutlineInputBorder(borderRadius: radius, borderSide: const BorderSide(color: AppColors.primary, width: 1.5)),
      errorBorder: OutlineInputBorder(borderRadius: radius, borderSide: const BorderSide(color: AppColors.error)),
      focusedErrorBorder: OutlineInputBorder(borderRadius: radius, borderSide: const BorderSide(color: AppColors.error, width: 1.5)),
      disabledBorder: OutlineInputBorder(borderRadius: radius, borderSide: const BorderSide(color: AppColors.border)),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: AppColors.primary,
        foregroundColor: Colors.white,
        disabledBackgroundColor: AppColors.neutralTint,
        disabledForegroundColor: const Color(0xFF9AA6B8),
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
        shape: RoundedRectangleBorder(borderRadius: radius),
        textStyle: const TextStyle(fontWeight: FontWeight.w600),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: AppColors.primary,
        side: const BorderSide(color: AppColors.border),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        shape: RoundedRectangleBorder(borderRadius: radius),
        textStyle: const TextStyle(fontWeight: FontWeight.w600),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: AppColors.primary,
        shape: RoundedRectangleBorder(borderRadius: radius),
        textStyle: const TextStyle(fontWeight: FontWeight.w600),
      ),
    ),
    chipTheme: ChipThemeData(
      backgroundColor: Colors.white,
      selectedColor: AppColors.primaryTint,
      side: const BorderSide(color: AppColors.border),
      labelStyle: const TextStyle(color: AppColors.text, fontWeight: FontWeight.w500, fontSize: 13),
      secondaryLabelStyle: const TextStyle(color: AppColors.primary, fontWeight: FontWeight.w600, fontSize: 13),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)),
      showCheckmark: false,
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
    ),
    tabBarTheme: const TabBarThemeData(
      labelColor: AppColors.primary,
      unselectedLabelColor: AppColors.textSecondary,
      indicatorColor: AppColors.primary,
      dividerColor: AppColors.border,
      labelStyle: TextStyle(fontWeight: FontWeight.w600, fontSize: 14),
      unselectedLabelStyle: TextStyle(fontWeight: FontWeight.w500, fontSize: 14),
    ),
    progressIndicatorTheme: const ProgressIndicatorThemeData(
      color: AppColors.primary,
      linearTrackColor: AppColors.neutralTint,
    ),
    tooltipTheme: TooltipThemeData(
      decoration: BoxDecoration(color: AppColors.text, borderRadius: BorderRadius.circular(6)),
      textStyle: const TextStyle(color: Colors.white, fontSize: 12),
      waitDuration: const Duration(milliseconds: 400),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: Colors.white,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(kRadius)),
    ),
    snackBarTheme: const SnackBarThemeData(behavior: SnackBarBehavior.floating),
  );
}
