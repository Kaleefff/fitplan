import { render, screen } from '@testing-library/react-native';
import type { ReactElement } from 'react';
import { View } from 'react-native';

import { AppThemeProvider } from '@/theme/theme-provider';

/**
 * Renders inside the app theme and waits until it has loaded: the provider renders
 * nothing until the saved preference is read.
 */
export async function renderWithTheme(ui: ReactElement) {
  const result = await render(
    <AppThemeProvider>
      <View testID="theme-ready">{ui}</View>
    </AppThemeProvider>,
  );
  await screen.findByTestId('theme-ready');
  return result;
}
