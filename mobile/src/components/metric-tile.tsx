import Ionicons from '@expo/vector-icons/Ionicons';
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
};

// Profile tile of the Home screen (Rys. 7.5): coloured icon, small label, large value
export function MetricTile({ icon, color, label, value }: MetricTileProps) {
  const { colors, radius, scheme } = useAppTheme();
  return (
    <Card style={styles.tile} accessible accessibilityLabel={`${label}: ${value}`}>
      <View style={[styles.icon, { borderRadius: radius.md, backgroundColor: colors[color] }]}>
        <Ionicons name={icon} size={20} color={scheme === 'dark' ? colors.background : '#FFFFFF'} />
      </View>
      <AppText variant="caption" color="textMuted">
        {label}
      </AppText>
      <AppText variant="title">{value}</AppText>
    </Card>
  );
}

const styles = StyleSheet.create({
  // Two tiles per row at any screen width
  tile: { flexBasis: '47%', flexGrow: 1 },
  icon: { width: 36, height: 36, alignItems: 'center', justifyContent: 'center' },
});
