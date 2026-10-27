import { fireEvent, screen } from '@testing-library/react-native';
import { router } from 'expo-router';

import HomeScreen from '@/app/(tabs)/index';
import { renderWithTheme } from '@/test-utils';

jest.mock('expo-router', () => ({ router: { push: jest.fn() } }));

let mockUser: { name: string } | null = null;
jest.mock('@/auth/session', () => ({
  useSession: () => ({ user: mockUser }),
}));

describe('HomeScreen', () => {
  it('greets the user by first name', async () => {
    mockUser = { name: 'Ola' };
    await renderWithTheme(<HomeScreen />);
    expect(screen.getByText('Welcome back, Ola!')).toBeOnTheScreen();
  });

  it('greets without a name when the backend does not send the user yet', async () => {
    mockUser = null;
    await renderWithTheme(<HomeScreen />);
    expect(screen.getByText('Welcome back!')).toBeOnTheScreen();
  });

  it('opens every module from its Quick Actions tile (M-07 Done)', async () => {
    await renderWithTheme(<HomeScreen />);
    const tiles = [
      ['Training Plan', '/training'],
      ['Diet Plan', '/diet'],
      ['AI Food Scanner', '/scan'],
      ['Analytics', '/stats'],
    ];
    for (const [title, href] of tiles) {
      await fireEvent.press(screen.getByRole('button', { name: new RegExp(`^${title}\\.`) }));
      expect(router.push).toHaveBeenLastCalledWith(href);
    }
  });
});
