import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import 'package:kilima_mobile/app_state.dart';
import 'package:kilima_mobile/main.dart';

void main() {
  testWidgets('L\'application se construit', (WidgetTester tester) async {
    await tester.pumpWidget(ChangeNotifierProvider(
        create: (_) => AppState(), child: const KilimaApp()));
    expect(find.byType(KilimaApp), findsOneWidget);
  });
}
