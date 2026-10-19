import { Text, type TextProps } from 'react-native';

import { useAppTheme } from '@/hooks/use-app-theme';
import type { ColorName, TypographyVariant } from '@/theme/tokens';

export type AppTextProps = TextProps & {
  variant?: TypographyVariant;
  color?: ColorName;
};

export function AppText({ variant = 'body', color = 'text', style, ...rest }: AppTextProps) {
  const theme = useAppTheme();
  return (
    <Text style={[theme.typography[variant], { color: theme.colors[color] }, style]} {...rest} />
  );
}
