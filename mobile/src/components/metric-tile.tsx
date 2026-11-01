import Ionicons from '@expo/vector-icons/Ionicons';
import type { ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';

import { AppText } from '@/components/app-text';
import { Card } from '@/components/card';
import type { IconName } from '@/constants/modules';
import { useAppTheme } from '@/hooks/use-app-theme';
import type { ColorName } from '@/theme/tokens';

type MetricTileProps = {
  icon: IconName;
  color: ColorName;
  label: string;
  value: string;
  /** Shown next to the label, for example a HelpButton */
  help?: ReactNode;
};

// Profile tile of the Home screen (Rys. 7.5): coloured icon, small label, large value
export function MetricTile({ icon, color, label, value, help }: MetricTileProps) {
  const { colors, radius, scheme, spacing } = useAppTheme();
  // A tile read as one element would hide the button inside it from a screen reader
  const summary = help ? {} : { accessible: true, accessibilityLabel: `${label}: ${value}` };
  return (
    <Card style={styles.tile} {...summary}>
      <View style={[styles.icon, { borderRadius: radius.md, backgroundColor: colors[color] }]}>
        <Ionicons name={icon} size={20} color={scheme === 'dark' ? colors.background : '#FFFFFF'} />
      </View>
      <View style={[styles.labelRow, { gap: spacing.xs }]}>
        <AppText variant="caption" color="textMuted">
          {label}
        </AppText>
        {help}
      </View>
      <AppText variant="title">{value}</AppText>
    </Card>
  );
}

const styles = StyleSheet.create({
  // Two tiles per row at any screen width
  tile: { flexBasis: '47%', flexGrow: 1 },
  icon: { width: 36, height: 36, alignItems: 'center', justifyContent: 'center' },
  labelRow: { flexDirection: 'row', alignItems: 'center' },
});
