import { router } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { fieldErrors, toApiError, userMessage } from '@/api/errors';
import { useSession } from '@/auth/session';
import { validateRegister, type RegisterForm } from '@/auth/validation';
import { AppText } from '@/components/app-text';
import { Button } from '@/components/button';
import { FormMessage } from '@/components/form-message';
import { Screen } from '@/components/screen';
import { TextField } from '@/components/text-field';
import { useAppTheme } from '@/hooks/use-app-theme';

const EMPTY: RegisterForm = { name: '', surname: '', email: '', password: '', repeatPassword: '' };

// "Create Account" (Rys. 7.2), FR-U1; the contract also requires name and surname
export default function SignUpScreen() {
  const { register } = useSession();
  const { colors, spacing } = useAppTheme();
  const [form, setForm] = useState<RegisterForm>(EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Editing a field clears its error
  const update = (field: keyof RegisterForm) => (value: string) => {
    setForm((current) => ({ ...current, [field]: value }));
    setErrors(({ [field]: _removed, ...rest }) => rest);
  };

  async function submit() {
    const found = validateRegister(form);
    setErrors(found);
    setMessage(null);
    if (Object.keys(found).length > 0) {
      return;
    }

    setBusy(true);
    try {
      // On success the session is signed in and the router leaves the auth screens
      await register({
        name: form.name.trim(),
        surname: form.surname.trim(),
        email: form.email.trim(),
        password: form.password,
      });
    } catch (error) {
      const apiError = toApiError(error);
      if (apiError.status === 409) {
        setErrors({ email: 'An account with this email already exists.' });
      } else if (apiError.code === 'validation_error') {
        setErrors(fieldErrors(apiError));
      } else {
        setMessage(userMessage(apiError));
      }
      setBusy(false);
    }
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }}>
      <Screen>
        <View style={{ gap: spacing.xs, marginTop: spacing.xl }}>
          <AppText variant="display">Create Account</AppText>
          <AppText color="textMuted">Start your personalised training and diet plan</AppText>
        </View>

        <FormMessage message={message} />

        <TextField
          label="First name"
          value={form.name}
          onChangeText={update('name')}
          error={errors.name}
          autoComplete="given-name"
          textContentType="givenName"
        />
        <TextField
          label="Last name"
          value={form.surname}
          onChangeText={update('surname')}
          error={errors.surname}
          autoComplete="family-name"
          textContentType="familyName"
        />
        <TextField
          label="Email"
          value={form.email}
          onChangeText={update('email')}
          error={errors.email}
          keyboardType="email-address"
          autoCapitalize="none"
          autoComplete="email"
          textContentType="emailAddress"
          placeholder="you@example.com"
        />
        <TextField
          label="Password"
          value={form.password}
          onChangeText={update('password')}
          error={errors.password}
          helper="8–72 characters, at least one letter and one digit"
          password
          autoComplete="new-password"
          textContentType="newPassword"
        />
        <TextField
          label="Repeat password"
          value={form.repeatPassword}
          onChangeText={update('repeatPassword')}
          error={errors.repeatPassword}
          password
          autoComplete="new-password"
          textContentType="newPassword"
          onSubmitEditing={submit}
        />

        <Button title="Create account" onPress={submit} loading={busy} />
        <Button title="I already have an account" variant="ghost" onPress={() => router.replace('/sign-in')} />
      </Screen>
    </SafeAreaView>
  );
}
