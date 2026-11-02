import { fireEvent, screen } from '@testing-library/react-native';

import OnboardingScreen from '@/app/onboarding';
import { monthsAgo } from '@/profile/options';
import { renderWithTheme } from '@/test-utils';

const mockCompleteProfile = jest.fn();
const mockSaveProfile = jest.fn();
const mockSaveAllergies = jest.fn();
const mockAddInjury = jest.fn();

jest.mock('@/auth/session', () => ({
  useSession: () => ({ completeProfile: mockCompleteProfile, signOut: jest.fn() }),
}));
jest.mock('@/profile/profile-api', () => ({
  loadReferenceLists: async () => ({
    injuryTypes: [
      { id: 1, type_name: 'Sprain', description: '', avg_healing_time_days: 14 },
      { id: 2, type_name: 'Strain', description: '', avg_healing_time_days: 21 },
      { id: 3, type_name: 'Knee pain', description: '', avg_healing_time_days: 28 },
    ],
    muscleGroups: [
      { id: 6, group_name: 'quadriceps', description: '', image_url: null },
      { id: 7, group_name: 'lower back', description: '', image_url: null },
    ],
    allergens: [{ id: 1, name: 'Gluten' }],
  }),
  saveProfile: (...args: unknown[]) => mockSaveProfile(...args),
  addInjury: (...args: unknown[]) => mockAddInjury(...args),
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

  it('explains PAL on the activity step', async () => {
    await renderWithTheme(<OnboardingScreen />);
    await fireEvent.changeText(screen.getByLabelText('Age'), '25');
    await choose('Male');
    await fireEvent.changeText(screen.getByLabelText('Weight'), '80');
    await fireEvent.changeText(screen.getByLabelText('Height'), '180');
    await press('Continue');

    await press('What is PAL?');
    expect(screen.getByText('How is it measured?')).toBeOnTheScreen();
  });

  async function goToHealthStep() {
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
    await screen.findByRole('checkbox', { name: 'Gluten' });
  }

  const chooseNth = (name: string, index: number) =>
    fireEvent.press(screen.getAllByRole('radio', { name })[index]);

  async function chooseDuration(index: number, name: string) {
    await fireEvent.press(screen.getAllByRole('button', { name: /^How long have you had it\?/ })[index]);
    await choose(name);
  }

  it('saves several injuries chosen at once, each with its own details', async () => {
    mockSaveProfile.mockResolvedValue({ age: 25, tdee: 2798 });
    mockAddInjury.mockResolvedValue({});
    await renderWithTheme(<OnboardingScreen />);
    await goToHealthStep();

    await press('+ Add injuries');
    await fireEvent.press(screen.getByRole('checkbox', { name: 'Sprain' }));
    await fireEvent.press(screen.getByRole('checkbox', { name: 'Strain' }));
    await chooseNth('Quadriceps', 0);
    await chooseNth('Mild', 0);
    await chooseDuration(0, 'Less than a month');
    await chooseNth('Lower back', 1);
    await chooseNth('Severe', 1);
    await chooseDuration(1, 'More than 3 years');
    await press('Add 2 injuries');
    await press('Finish');

    expect(mockAddInjury).toHaveBeenCalledTimes(2);
    expect(mockAddInjury).toHaveBeenNthCalledWith(1, {
      injury_type_id: 1,
      affected_muscle_group_id: 6,
      severity: 'mild',
      start_date: monthsAgo(0),
      is_active: true,
    });
    expect(mockAddInjury).toHaveBeenNthCalledWith(2, {
      injury_type_id: 2,
      affected_muscle_group_id: 7,
      severity: 'severe',
      start_date: monthsAgo(36),
      is_active: true,
    });
  });

  it('does not ask for the muscles when the injury type names them', async () => {
    mockSaveProfile.mockResolvedValue({ age: 25, tdee: 2798 });
    mockAddInjury.mockResolvedValue({});
    await renderWithTheme(<OnboardingScreen />);
    await goToHealthStep();

    await press('+ Add injuries');
    await fireEvent.press(screen.getByRole('checkbox', { name: 'Knee pain' }));
    expect(screen.queryByText('Which muscles should your plan spare?')).not.toBeOnTheScreen();
    expect(screen.getByText('Your plan will leave out quadriceps exercises.')).toBeOnTheScreen();

    await chooseNth('Moderate', 0);
    await chooseDuration(0, '1–3 years');
    await press('Add injury');
    expect(screen.getByText('Quadriceps · Moderate · 1–3 years')).toBeOnTheScreen();
    await press('Finish');

    expect(mockAddInjury).toHaveBeenCalledWith({
      injury_type_id: 3,
      affected_muscle_group_id: 6,
      severity: 'moderate',
      start_date: monthsAgo(12),
      is_active: true,
    });
  });

  it('does not add injuries until every chosen type has its details', async () => {
    await renderWithTheme(<OnboardingScreen />);
    await goToHealthStep();

    await press('+ Add injuries');
    await press('Add injury');
    expect(screen.getByText('Choose at least one type of injury.')).toBeOnTheScreen();

    await fireEvent.press(screen.getByRole('checkbox', { name: 'Sprain' }));
    await fireEvent.press(screen.getByRole('checkbox', { name: 'Strain' }));
    await chooseNth('Quadriceps', 0);
    await chooseNth('Mild', 0);
    await chooseDuration(0, '1–12 months');
    await press('Add 2 injuries');

    expect(screen.getByText('Choose the muscles to spare.')).toBeOnTheScreen();
    expect(screen.getByText('Choose how severe it is.')).toBeOnTheScreen();
    expect(screen.getByText('Choose how long you have had it.')).toBeOnTheScreen();
    expect(screen.queryByRole('button', { name: 'Remove' })).not.toBeOnTheScreen();
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
