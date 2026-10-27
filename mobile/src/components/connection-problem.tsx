import { StyleSheet, View } from 'react-native';

import { useSession } from '@/auth/session';
import { AppText } from '@/components/app-text';
import { Button } from '@/components/button';
import { useAppTheme } from '@/hooks/use-app-theme';
import { config } from '@/config';

// Shown at launch when a stored session exists but the server cannot be reached
export function ConnectionProblem() {
  const { problem, retry, signOut } = useSession();
  const { colors, spacing } = useAppTheme();

  return (
    <View style={[styles.fill, { backgroundColor: colors.background, padding: spacing.xl, gap: spacing.lg }]}>
      <AppText variant="headline">Cannot connect</AppText>
      <AppText>{problem}</AppText>
      <AppText variant="caption" color="textMuted">
        Server: {config.apiUrl}
      </AppText>
      <Button title="Try again" onPress={retry} />
      <Button title="Sign out" variant="ghost" onPress={signOut} />
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1, justifyContent: 'center' },
});
