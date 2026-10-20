import type { TextStyle } from 'react-native';

export type ColorScheme = 'light' | 'dark';

export const lightColors = {
  background: '#F9FAFB',
  surface: '#FFFFFF',
  surfaceAlt: '#F3F4F6',
  border: '#E5E7EB',
  text: '#111827',
  textMuted: '#4B5563',
  primary: '#2563EB',
  onPrimary: '#FFFFFF',
  success: '#16A34A',
  warning: '#D97706',
  danger: '#DC2626',

  training: '#2563EB',
  trainingTint: '#EFF6FF',
  diet: '#16A34A',
  dietTint: '#F0FDF4',
  scanner: '#9333EA',
  scannerTint: '#FAF5FF',
  analytics: '#EA580C',
  analyticsTint: '#FFF7ED',

  kcal: '#2563EB',
  protein: '#9333EA',
  carbs: '#EA580C',
  fat: '#CA8A04',
} satisfies Record<string, string>;

export type ColorName = keyof typeof lightColors;
export type ThemeColors = Record<ColorName, string>;

export const darkColors: ThemeColors = {
  background: '#0F172A',
  surface: '#1E293B',
  surfaceAlt: '#273449',
  border: '#334155',
  text: '#F1F5F9',
  textMuted: '#94A3B8',
  primary: '#60A5FA',
  onPrimary: '#0F172A',
  success: '#4ADE80',
  warning: '#FBBF24',
  danger: '#F87171',

  training: '#60A5FA',
  trainingTint: 'rgba(96, 165, 250, 0.16)',
  diet: '#4ADE80',
  dietTint: 'rgba(74, 222, 128, 0.16)',
  scanner: '#C084FC',
  scannerTint: 'rgba(192, 132, 252, 0.16)',
  analytics: '#FB923C',
  analyticsTint: 'rgba(251, 146, 60, 0.16)',

  kcal: '#60A5FA',
  protein: '#C084FC',
  carbs: '#FB923C',
  fat: '#FACC15',
};

export const colors: Record<ColorScheme, ThemeColors> = {
  light: lightColors,
  dark: darkColors,
};

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
} as const;

export const radius = {
  sm: 8,
  md: 12,
  lg: 16,
  pill: 999,
} as const;

export const typography = {
  caption: { fontSize: 12, lineHeight: 16, fontWeight: '400' },
  body: { fontSize: 14, lineHeight: 20, fontWeight: '400' },
  bodyStrong: { fontSize: 14, lineHeight: 20, fontWeight: '600' },
  bodyLarge: { fontSize: 16, lineHeight: 24, fontWeight: '400' },
  title: { fontSize: 18, lineHeight: 24, fontWeight: '600' },
  headline: { fontSize: 22, lineHeight: 28, fontWeight: '700' },
  display: { fontSize: 28, lineHeight: 34, fontWeight: '700' },
} satisfies Record<string, TextStyle>;

export type TypographyVariant = keyof typeof typography;

export const minTouchSize = 48;
