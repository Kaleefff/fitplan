import { useState } from 'react';
import { Pressable, StyleSheet, TextInput, View, type TextInputProps } from 'react-native';

import { AppText } from '@/components/app-text';
import { useAppTheme } from '@/hooks/use-app-theme';
import { minTouchSize } from '@/theme/tokens';

type TextFieldProps = Omit<TextInputProps, 'style'> & {
  label: string;
  /** Shown under the field in red; also announced by screen readers */
  error?: string;
  /** Grey hint under the field when there is no error */
  helper?: string;
  /** Text after the value, for example "kg" */
  unit?: string;
  /** Adds a Show/Hide button and hides the text by default */
  password?: boolean;
};

export function TextField({ label, error, helper, unit, password = false, ...inputProps }: TextFieldProps) {
  const { colors, radius, spacing, typography } = useAppTheme();
  const [hidden, setHidden] = useState(password);

  return (
    <View style={{ gap: spacing.xs }}>
      <AppText variant="bodyStrong">{label}</AppText>
      <View
        style={[
          styles.box,
          {
            backgroundColor: colors.surface,
            borderColor: error ? colors.danger : colors.border,
            borderRadius: radius.md,
            paddingHorizontal: spacing.md,
          },
        ]}>
        <TextInput
          accessibilityLabel={label}
          accessibilityHint={error}
          placeholderTextColor={colors.textMuted}
          secureTextEntry={hidden}
          autoCapitalize={password ? 'none' : inputProps.autoCapitalize}
          {...inputProps}
          style={[styles.input, typography.bodyLarge, { color: colors.text }]}
        />
        {unit ? <AppText color="textMuted">{unit}</AppText> : null}
        {password ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={hidden ? 'Show password' : 'Hide password'}
            onPress={() => setHidden((value) => !value)}
            hitSlop={spacing.sm}
            style={styles.toggle}>
            <AppText variant="bodyStrong" color="primary">
              {hidden ? 'Show' : 'Hide'}
            </AppText>
          </Pressable>
        ) : null}
      </View>
      {error ? (
        <AppText variant="caption" color="danger" accessibilityLiveRegion="polite">
          {error}
        </AppText>
      ) : helper ? (
        <AppText variant="caption" color="textMuted">
          {helper}
        </AppText>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  box: {
    minHeight: minTouchSize,
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    gap: 8,
  },
  input: { flex: 1, paddingVertical: 10 },
  toggle: { paddingLeft: 4 },
});
