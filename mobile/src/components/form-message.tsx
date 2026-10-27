import { View } from 'react-native';

import { AppText } from '@/components/app-text';
import { useAppTheme } from '@/hooks/use-app-theme';

type FormMessageProps = {
  /** Nothing is rendered without a message */
  message: string | null | undefined;
  tone?: 'error' | 'info';
};

// Box above a form for errors that belong to no single field (wrong password, no connection)
export function FormMessage({ message, tone = 'error' }: FormMessageProps) {
  const { colors, radius, spacing } = useAppTheme();
  if (!message) {
    return null;
  }
  const color = tone === 'error' ? colors.danger : colors.primary;
  return (
    <View
      accessibilityRole={tone === 'error' ? 'alert' : undefined}
      accessibilityLiveRegion="polite"
      style={{
        borderColor: color,
        borderWidth: 1,
        borderLeftWidth: 4,
        borderRadius: radius.md,
        padding: spacing.md,
        backgroundColor: colors.surface,
      }}>
      <AppText color={tone === 'error' ? 'danger' : 'text'}>{message}</AppText>
    </View>
  );
}
