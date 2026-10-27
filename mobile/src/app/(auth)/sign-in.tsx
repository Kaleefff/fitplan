import { router } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { fieldErrors, toApiError, userMessage } from '@/api/errors';
import { useSession } from '@/auth/session';
import { checkEmail } from '@/auth/validation';
import { AppText } from '@/components/app-text';
import { Button } from '@/components/button';
import { FormMessage } from '@/components/form-message';
import { Screen } from '@/components/screen';
import { TextField } from '@/components/text-field';
import { useAppTheme } from '@/hooks/use-app-theme';

// "Welcome Back" (Rys. 7.1), FR-U2
export default function SignInScreen() {
  const { signIn } = useSession();
  const { colors, spacing } = useAppTheme();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    const missing: Record<string, string> = {};
    const emailError = checkEmail(email);
    if (emailError) {
      missing.email = emailError;
    }
    if (!password) {
      missing.password = 'Enter your password.';
    }
    setErrors(missing);
    setMessage(null);
    if (Object.keys(missing).length > 0) {
      return;
    }

    setBusy(true);
    try {
      // On success the session switches to signed in and the router opens Home
      await signIn(email.trim(), password);
    } catch (error) {
      const apiError = toApiError(error);
      if (apiError.code === 'invalid_credentials') {
        setMessage('Email or password is incorrect.');
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
          <AppText variant="display">Welcome Back</AppText>
          <AppText color="textMuted">Sign in to continue your plan</AppText>
        </View>

        <FormMessage message={message} />

        <TextField
          label="Email"
          value={email}
          onChangeText={setEmail}
          error={errors.email}
          keyboardType="email-address"
          autoCapitalize="none"
          autoComplete="email"
          textContentType="emailAddress"
          placeholder="you@example.com"
        />
        <TextField
          label="Password"
          value={password}
          onChangeText={setPassword}
          error={errors.password}
          password
          autoComplete="current-password"
          textContentType="password"
          onSubmitEditing={submit}
        />

        <Button title="Sign in" onPress={submit} loading={busy} />
        <Button title="Create an account" variant="ghost" onPress={() => router.replace('/sign-up')} />
      </Screen>
    </SafeAreaView>
  );
}
