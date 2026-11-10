import { fireEvent, screen } from '@testing-library/react-native';

import EditProfileScreen from '@/app/edit-profile';
import { renderWithTheme } from '@/test-utils';

const mockNavigate = jest.fn();
jest.mock('expo-router', () => ({ router: { navigate: (...args: unknown[]) => mockNavigate(...args) } }));

const mockCompleteProfile = jest.fn();
const mockSetUser = jest.fn();
const profile = {
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
  profile_update: '2026-11-01T10:00:00Z',
};
jest.mock('@/auth/session', () => ({
  useSession: () => ({
    user: { id: 1, email: 'ola@example.com', name: 'Ola', surname: 'Nowak', timezone: 'Europe/Warsaw' },
    profile,
    completeProfile: mockCompleteProfile,
    updateUser: mockSetUser,
  }),
}));

const mockApi = {
  saveProfile: jest.fn(),
  addInjury: jest.fn(),
  updateInjury: jest.fn(),
  deleteInjury: jest.fn(),
  saveAllergies: jest.fn(),
  updateUser: jest.fn(),
  getInjuries: jest.fn(),
};
jest.mock('@/profile/profile-api', () => ({
  loadReferenceLists: async () => ({
    injuryTypes: [
      { id: 1, type_name: 'Wrist sprain', description: '', avg_healing_time_days: 21 },
      { id: 3, type_name: 'Knee pain', description: '', avg_healing_time_days: 28 },
      { id: 4, type_name: 'Calf strain', description: '', avg_healing_time_days: 21 },
    ],
    muscleGroups: [
      { id: 6, group_name: 'quadriceps', description: '', image_url: null },
      { id: 9, group_name: 'calves', description: '', image_url: null },
    ],
    allergens: [
      { id: 1, name: 'Gluten', description: '' },
      { id: 2, name: 'Lactose', description: '' },
    ],
  }),
  getAllergies: async () => [{ id: 1, name: 'Gluten', description: '' }],
  getInjuries: () => mockApi.getInjuries(),
  saveProfile: (...args: unknown[]) => mockApi.saveProfile(...args),
  addInjury: (...args: unknown[]) => mockApi.addInjury(...args),
  updateInjury: (...args: unknown[]) => mockApi.updateInjury(...args),
  deleteInjury: (...args: unknown[]) => mockApi.deleteInjury(...args),
  saveAllergies: (...args: unknown[]) => mockApi.saveAllergies(...args),
  updateUser: (...args: unknown[]) => mockApi.updateUser(...args),
}));

const mockGetActivePlan = jest.fn();
const mockGeneratePlan = jest.fn();
jest.mock('@/training/training-api', () => ({
  ...jest.requireActual('@/training/training-api'),
  getActivePlan: () => mockGetActivePlan(),
  generatePlan: (...args: unknown[]) => mockGeneratePlan(...args),
}));

const kneeInjury = {
  id: 7,
  injury_type_id: 3,
  affected_muscle_group_id: 6,
  severity: 'moderate',
  start_date: '2026-10-01',
  is_active: true,
};

const press = (name: string) => fireEvent.press(screen.getByRole('button', { name }));

describe('EditProfileScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockApi.getInjuries.mockResolvedValue([kneeInjury]);
    mockGetActivePlan.mockResolvedValue(null);
  });

  it('starts from the saved profile and saves only what changed', async () => {
    mockApi.saveProfile.mockResolvedValue({ ...profile, current_weight: 78.5 });
    await renderWithTheme(<EditProfileScreen />);
    await screen.findByText('Knee pain');

    expect(screen.getByLabelText('Weight')).toHaveDisplayValue('80');
    await fireEvent.changeText(screen.getByLabelText('Weight'), '78,5');
    await press('Save changes');

    expect(mockApi.saveProfile).toHaveBeenCalledWith(expect.objectContaining({ current_weight: 78.5, age: 25 }));
    expect(mockCompleteProfile).toHaveBeenCalledWith(expect.objectContaining({ current_weight: 78.5 }));
    expect(mockApi.updateUser).not.toHaveBeenCalled();
    expect(mockApi.saveAllergies).not.toHaveBeenCalled();
    expect(await screen.findByText('Your profile is saved.')).toBeOnTheScreen();
    expect(screen.queryByText('Your injuries changed. Generate a new plan?')).not.toBeOnTheScreen();
  });

  it('checks the ranges and the name before saving', async () => {
    await renderWithTheme(<EditProfileScreen />);
    await screen.findByText('Knee pain');
    await fireEvent.changeText(screen.getByLabelText('Weight'), '301');
    await fireEvent.changeText(screen.getByLabelText('First name'), ' ');
    await press('Save changes');

    expect(screen.getByText('Weight must be between 30 and 300 kg.')).toBeOnTheScreen();
    expect(screen.getByText('Enter your first name.')).toBeOnTheScreen();
    expect(mockApi.saveProfile).not.toHaveBeenCalled();
  });

  it('heals an injury, changes allergies and the name, then offers a new plan', async () => {
    const active = { id: 1, goal: 'strength', num_training_days: 3, experience_level: 'beginner', equipment: 'gym' };
    mockGetActivePlan.mockResolvedValue(active);
    mockApi.updateInjury.mockResolvedValue({});
    mockApi.saveAllergies.mockResolvedValue([]);
    mockApi.updateUser.mockResolvedValue({ name: 'Ola', surname: 'Kowalska' });
    mockGeneratePlan.mockResolvedValue({ id: 5 });
    await renderWithTheme(<EditProfileScreen />);
    await screen.findByText('Knee pain');

    await press('Healed');
    expect(screen.getByText('Marked as healed when you save')).toBeOnTheScreen();
    await fireEvent.press(screen.getByRole('checkbox', { name: 'Lactose' }));
    await fireEvent.changeText(screen.getByLabelText('Last name'), 'Kowalska');
    await press('Save changes');

    expect(mockApi.updateUser).toHaveBeenCalledWith({ name: 'Ola', surname: 'Kowalska' });
    expect(mockSetUser).toHaveBeenCalledWith({ name: 'Ola', surname: 'Kowalska' });
    expect(mockApi.saveProfile).not.toHaveBeenCalled();
    expect(mockApi.updateInjury).toHaveBeenCalledWith(7, { is_active: false });
    expect(mockApi.saveAllergies).toHaveBeenCalledWith([1, 2]);

    expect(await screen.findByText('Your injuries changed. Generate a new plan?')).toBeOnTheScreen();
    await press('Generate new plan');
    expect(mockGeneratePlan).toHaveBeenCalledWith({
      goal: 'strength',
      num_training_days: 3,
      experience_level: 'beginner',
      equipment: 'gym',
    });
    expect(mockNavigate).toHaveBeenCalledWith('/training');
  });

  it('does not add an injury twice when a save is repeated after an error', async () => {
    mockApi.addInjury.mockResolvedValueOnce({}).mockRejectedValueOnce(new TypeError('Network request failed'));
    await renderWithTheme(<EditProfileScreen />);
    await screen.findByText('Knee pain');

    await press('+ Add injuries');
    await fireEvent.press(screen.getByRole('checkbox', { name: 'Calf strain' }));
    await fireEvent.press(screen.getByRole('checkbox', { name: 'Wrist sprain' }));
    await fireEvent.press(screen.getAllByRole('radio', { name: 'Mild' })[0]);
    await fireEvent.press(screen.getAllByRole('radio', { name: 'Calves' })[0]);
    await fireEvent.press(screen.getAllByRole('radio', { name: 'Mild' })[1]);
    for (const field of screen.getAllByRole('button', { name: /^How long have you had it\?/ })) {
      await fireEvent.press(field);
      await fireEvent.press(screen.getByRole('radio', { name: 'Less than a month' }));
    }
    await press('Add 2 injuries');
    await press('Save changes');

    expect(mockApi.addInjury).toHaveBeenCalledTimes(2);
    expect(screen.getByText('Cannot reach the server. Check your internet connection and try again.')).toBeOnTheScreen();

    mockApi.addInjury.mockResolvedValue({});
    await press('Save changes');
    expect(mockApi.addInjury).toHaveBeenCalledTimes(3);
    expect(mockApi.addInjury).toHaveBeenLastCalledWith(expect.objectContaining({ injury_type_id: 1 }));
  });
});
