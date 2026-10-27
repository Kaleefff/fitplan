import { fireEvent, screen } from '@testing-library/react-native';

import { Button } from '@/components/button';
import { MultiOptionGroup, OptionGroup } from '@/components/option-group';
import { TextField } from '@/components/text-field';
import { renderWithTheme } from '@/test-utils';

describe('Button', () => {
  it('calls onPress', async () => {
    const onPress = jest.fn();
    await renderWithTheme(<Button title="Sign in" onPress={onPress} />);
    await fireEvent.press(screen.getByRole('button', { name: 'Sign in' }));
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it('ignores presses while loading', async () => {
    const onPress = jest.fn();
    await renderWithTheme(<Button title="Sign in" onPress={onPress} loading testID="submit" />);
    await fireEvent.press(screen.getByTestId('submit'));
    expect(onPress).not.toHaveBeenCalled();
  });
});

describe('TextField', () => {
  it('shows the error under the field', async () => {
    await renderWithTheme(<TextField label="Email" value="" error="Enter a valid email address." />);
    expect(screen.getByText('Enter a valid email address.')).toBeOnTheScreen();
  });

  it('hides a password until Show is pressed', async () => {
    await renderWithTheme(<TextField label="Password" value="secret123" password />);
    expect(screen.getByLabelText('Password').props.secureTextEntry).toBe(true);
    await fireEvent.press(screen.getByRole('button', { name: 'Show password' }));
    expect(screen.getByLabelText('Password').props.secureTextEntry).toBe(false);
  });
});

describe('OptionGroup', () => {
  const options = [
    { value: 'male' as const, label: 'Male' },
    { value: 'female' as const, label: 'Female' },
  ];

  it('reports the chosen value', async () => {
    const onChange = jest.fn();
    await renderWithTheme(<OptionGroup label="Sex" options={options} value={null} onChange={onChange} />);
    await fireEvent.press(screen.getByRole('radio', { name: 'Female' }));
    expect(onChange).toHaveBeenCalledWith('female');
  });

  it('adds and removes values in the multiple variant', async () => {
    const onChange = jest.fn();
    await renderWithTheme(
      <MultiOptionGroup
        label="Training days"
        options={[
          { value: 1, label: 'Monday' },
          { value: 2, label: 'Tuesday' },
        ]}
        values={[1]}
        onChange={onChange}
      />,
    );
    await fireEvent.press(screen.getByRole('checkbox', { name: 'Tuesday' }));
    expect(onChange).toHaveBeenLastCalledWith([1, 2]);
    await fireEvent.press(screen.getByRole('checkbox', { name: 'Monday' }));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });
});
