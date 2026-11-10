import AsyncStorage from '@react-native-async-storage/async-storage';
import { render, waitFor } from '@testing-library/react-native';
import * as SystemUI from 'expo-system-ui';
import { Text } from 'react-native';

import { AppThemeProvider } from '@/theme/theme-provider';
import { colors } from '@/theme/tokens';

jest.mock('expo-system-ui', () => ({ setBackgroundColorAsync: jest.fn(() => Promise.resolve()) }));

describe('AppThemeProvider', () => {
  it('gives the window behind the screens the colour of the chosen theme', async () => {
    // Dark chosen in Settings, whatever the phone uses: closing a screen must not flash white
    await AsyncStorage.setItem('theme.preference', 'dark');
    await render(
      <AppThemeProvider>
        <Text>content</Text>
      </AppThemeProvider>,
    );

    await waitFor(() => expect(SystemUI.setBackgroundColorAsync).toHaveBeenCalledWith(colors.dark.background));
  });
});
