import 'package:material_ui/material_ui.dart';

/// A TextField whose text follows [value] when it changes from outside
/// (e.g. a preset was applied) without disturbing the cursor while typing.
class SyncedTextField extends StatefulWidget {
  const SyncedTextField({
    super.key,
    required this.value,
    required this.onChanged,
    this.decoration = const InputDecoration(),
    this.onSubmitted,
    this.enabled = true,
    this.textAlign = TextAlign.start,
    this.keyboardType,
    this.style,
  });

  final String value;
  final ValueChanged<String> onChanged;
  final ValueChanged<String>? onSubmitted;
  final InputDecoration decoration;
  final bool enabled;
  final TextAlign textAlign;
  final TextInputType? keyboardType;
  final TextStyle? style;

  @override
  State<SyncedTextField> createState() => _SyncedTextFieldState();
}

class _SyncedTextFieldState extends State<SyncedTextField> {
  late final TextEditingController _c = TextEditingController(text: widget.value);

  @override
  void didUpdateWidget(SyncedTextField old) {
    super.didUpdateWidget(old);
    if (widget.value != _c.text) {
      _c.value = TextEditingValue(
        text: widget.value,
        selection: TextSelection.collapsed(offset: widget.value.length),
      );
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => TextField(
        controller: _c,
        onChanged: widget.onChanged,
        onSubmitted: widget.onSubmitted,
        decoration: widget.decoration,
        enabled: widget.enabled,
        textAlign: widget.textAlign,
        keyboardType: widget.keyboardType,
        style: widget.style,
      );
}
