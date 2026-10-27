import { fireEvent, screen } from '@testing-library/react-native';

import { ApiError } from '@/api/errors';
import SignUpScreen from '@/app/(auth)/sign-up';
import { renderWithTheme } from '@/test-utils';

const mockRegister = jest.fn();

jest.mock('@/auth/session', () => ({
  useSession: () => ({ register: mockRegister }),
}));
jest.mock('expo-router', () => ({ router: { replace: jest.fn() } }));

async function fillValidForm() {
  await fireEvent.changeText(screen.getByLabelText('First name'), 'Ola');
  await fireEvent.changeText(screen.getByLabelText('Last name'), 'Nowak');
  await fireEvent.changeText(screen.getByLabelText('Email'), 'ola@example.com');
  await fireEvent.changeText(screen.getByLabelText('Password'), 'secret123');
  await fireEvent.changeText(screen.getByLabelText('Repeat password'), 'secret123');
}

describe('SignUpScreen', () => {
  beforeEach(() => mockRegister.mockReset());

  it('shows field errors and does not call the API for an invalid form', async () => {
    await renderWithTheme(<SignUpScreen />);
    await fireEvent.press(screen.getByRole('button', { name: 'Create account' }));
    expect(screen.getByText('Enter your first name.')).toBeOnTheScreen();
    expect(screen.getByText('Enter your email.')).toBeOnTheScreen();
    expect(mockRegister).not.toHaveBeenCalled();
  });

  it('sends the trimmed form', async () => {
    mockRegister.mockResolvedValue(undefined);
    await renderWithTheme(<SignUpScreen />);
    await fillValidForm();
    await fireEvent.changeText(screen.getByLabelText('First name'), '  Ola ');
    await fireEvent.press(screen.getByRole('button', { name: 'Create account' }));
    expect(mockRegister).toHaveBeenCalledWith({
      name: 'Ola',
      surname: 'Nowak',
      email: 'ola@example.com',
      password: 'secret123',
    });
  });

  it('puts a taken email (409) under the email field', async () => {
    mockRegister.mockRejectedValue(new ApiError(409, 'conflict', 'Email already registered'));
    await renderWithTheme(<SignUpScreen />);
    await fillValidForm();
    await fireEvent.press(screen.getByRole('button', { name: 'Create account' }));
    expect(await screen.findByText('An account with this email already exists.')).toBeOnTheScreen();
  });

  it('shows server validation errors next to the right field (M-04 Done)', async () => {
    mockRegister.mockRejectedValue(
      new ApiError(422, 'validation_error', 'Request validation failed', [
        { field: 'body.surname', code: 'string_too_long', message: 'String should have at most 100 characters' },
      ]),
    );
    await renderWithTheme(<SignUpScreen />);
    await fillValidForm();
    await fireEvent.press(screen.getByRole('button', { name: 'Create account' }));
    expect(await screen.findByText('String should have at most 100 characters')).toBeOnTheScreen();
  });
});
