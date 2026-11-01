import { fireEvent, screen } from '@testing-library/react-native';
import { router } from 'expo-router';

import HomeScreen from '@/app/(tabs)/index';
import { renderWithTheme } from '@/test-utils';

jest.mock('expo-router', () => ({ router: { push: jest.fn() } }));
let mockUser: { name: string } | null = { name: 'Ola' };
jest.mock('@/auth/session', () => ({
  useSession: () => ({
    user: mockUser,
    profile: {
      age: 25,
      sex: 'male',
      current_weight: 80,
      height: 180,
      activity_level_pal: 1.55,
      goal: 'muscle_gain',
      target_value: null,
      experience_level: 'beginner',
      equipment: 'gym',
      tdee: 2798,
      profile_update: '2026-10-26T12:00:00Z',
    },
  }),
}));
// algorithms.md section 2, first vector
jest.mock('@/api/client', () => ({
  api: {
    GET: async () => ({
      data: { goal: 'muscle_gain', bmr: 1805, tdee: 2798, target_kcal: 3078, protein_g: 144, fat_g: 85.5, carbs_g: 433.1 },
      response: { ok: true, status: 200 },
    }),
  },
  unwrap: async (call: Promise<{ data: unknown }>) => (await call).data,
}));

describe('HomeScreen', () => {
  beforeEach(() => {
    mockUser = { name: 'Ola' };
  });

  it('greets without a name while the backend does not serve GET /users/me', async () => {
    mockUser = null;
    await renderWithTheme(<HomeScreen />);
    expect(screen.getByText('Welcome back!')).toBeOnTheScreen();
    expect(await screen.findByText('3078')).toBeOnTheScreen();
  });

  it('shows the user, the profile tiles and the daily target', async () => {
    await renderWithTheme(<HomeScreen />);
    expect(screen.getByText('Welcome back, Ola!')).toBeOnTheScreen();
    expect(screen.getByLabelText('Current weight: 80 kg')).toBeOnTheScreen();
    expect(screen.getByLabelText('Goal: Muscle gain')).toBeOnTheScreen();
    expect(screen.getByLabelText('Training level: Beginner')).toBeOnTheScreen();
    expect(screen.getByText('Activity level')).toBeOnTheScreen();
    expect(screen.getByText('PAL 1.55')).toBeOnTheScreen();
    expect(await screen.findByText('3078')).toBeOnTheScreen();
    expect(screen.getByLabelText('Protein 144 grams')).toBeOnTheScreen();
  });

  it('explains PAL from the button next to the activity level', async () => {
    await renderWithTheme(<HomeScreen />);
    expect(screen.queryByText('How is it measured?')).not.toBeOnTheScreen();

    await fireEvent.press(screen.getByRole('button', { name: 'What is PAL?' }));
    expect(screen.getByText('How is it measured?')).toBeOnTheScreen();
    expect(screen.getByText('Moderate (PAL 1.55)')).toBeOnTheScreen();
    expect(screen.getByText('Moderate exercise 3–5 days a week')).toBeOnTheScreen();

    await fireEvent.press(screen.getByRole('button', { name: 'Got it' }));
    expect(screen.queryByText('How is it measured?')).not.toBeOnTheScreen();
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
