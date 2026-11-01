import { fireEvent, screen } from '@testing-library/react-native';

import OnboardingScreen from '@/app/onboarding';
import { renderWithTheme } from '@/test-utils';

const mockCompleteProfile = jest.fn();
const mockSaveProfile = jest.fn();
const mockSaveAllergies = jest.fn();

jest.mock('@/auth/session', () => ({
  useSession: () => ({ completeProfile: mockCompleteProfile, signOut: jest.fn() }),
}));
jest.mock('@/profile/profile-api', () => ({
  loadReferenceLists: async () => ({
    injuryTypes: [{ id: 1, type_name: 'Sprain', description: '', avg_healing_time_days: 14 }],
    muscleGroups: [{ id: 6, group_name: 'quadriceps', description: '', image_url: null }],
    allergens: [{ id: 1, name: 'Gluten' }],
  }),
  saveProfile: (...args: unknown[]) => mockSaveProfile(...args),
  addInjury: jest.fn(),
  saveAllergies: (...args: unknown[]) => mockSaveAllergies(...args),
}));

const press = (name: string) => fireEvent.press(screen.getByRole('button', { name }));
const choose = (name: string) => fireEvent.press(screen.getByRole('radio', { name }));

describe('OnboardingScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('does not continue with a weight out of range (M-06 Done)', async () => {
    await renderWithTheme(<OnboardingScreen />);
    await fireEvent.changeText(screen.getByLabelText('Age'), '25');
    await choose('Male');
    await fireEvent.changeText(screen.getByLabelText('Weight'), '301');
    await fireEvent.changeText(screen.getByLabelText('Height'), '180');
    await press('Continue');

    expect(screen.getByText('Weight must be between 30 and 300 kg.')).toBeOnTheScreen();
    expect(screen.getByText('Step 1 of 4')).toBeOnTheScreen();
  });

  it('saves the profile and the allergies, then finishes', async () => {
    mockSaveProfile.mockResolvedValue({ age: 25, tdee: 2798 });
    mockSaveAllergies.mockResolvedValue([]);
    await renderWithTheme(<OnboardingScreen />);

    await fireEvent.changeText(screen.getByLabelText('Age'), '25');
    await choose('Male');
    await fireEvent.changeText(screen.getByLabelText('Weight'), '80');
    await fireEvent.changeText(screen.getByLabelText('Height'), '180');
    await press('Continue');
    await choose('Moderate, PAL 1.55');
    await choose('Muscle gain');
    await press('Continue');
    await choose('Beginner');
    await choose('Gym, Full gym');
    await press('Continue');
    await fireEvent.press(await screen.findByRole('checkbox', { name: 'Gluten' }));
    await press('Finish');

    expect(mockSaveProfile).toHaveBeenCalledWith({
      age: 25,
      sex: 'male',
      current_weight: 80,
      height: 180,
      activity_level_pal: 1.55,
      goal: 'muscle_gain',
      target_value: null,
      experience_level: 'beginner',
      equipment: 'gym',
    });
    expect(mockSaveAllergies).toHaveBeenCalledWith([1]);
    expect(mockCompleteProfile).toHaveBeenCalledWith({ age: 25, tdee: 2798 });
  });
});
