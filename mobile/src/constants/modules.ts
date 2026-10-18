import type Ionicons from '@expo/vector-icons/Ionicons';
import type { ComponentProps } from 'react';

import type { ColorName } from '@/theme/tokens';

export type IconName = ComponentProps<typeof Ionicons>['name'];

export type ModuleKey = 'training' | 'scan' | 'diet' | 'stats';

export type AppModule = {
  key: ModuleKey;
  /** Route of the tab, e.g. /training */
  href: `/${ModuleKey}`;
  /** Label in the tab bar */
  tabLabel: string;
  title: string;
  description: string;
  icon: IconName;
  color: ColorName;
  tint: ColorName;
};

// Main sections of the app; texts follow the Home screen mockup (Rys. 7.5)
export const MODULES: AppModule[] = [
  {
    key: 'training',
    href: '/training',
    tabLabel: 'Training',
    title: 'Training Plan',
    description: 'Generate personalized workout routines',
    icon: 'barbell-outline',
    color: 'training',
    tint: 'trainingTint',
  },
  {
    key: 'diet',
    href: '/diet',
    tabLabel: 'Diet',
    title: 'Diet Plan',
    description: 'Create customized nutrition plans',
    icon: 'restaurant-outline',
    color: 'diet',
    tint: 'dietTint',
  },
  {
    key: 'scan',
    href: '/scan',
    tabLabel: 'Scan',
    title: 'AI Food Scanner',
    description: 'Scan meals and track nutrition',
    icon: 'camera-outline',
    color: 'scanner',
    tint: 'scannerTint',
  },
  {
    key: 'stats',
    href: '/stats',
    tabLabel: 'Stats',
    title: 'Analytics',
    description: 'Track your progress over time',
    icon: 'stats-chart-outline',
    color: 'analytics',
    tint: 'analyticsTint',
  },
];

export function getModule(key: ModuleKey): AppModule {
  const found = MODULES.find((module) => module.key === key);
  if (!found) {
    throw new Error(`Unknown module: ${key}`);
  }
  return found;
}
