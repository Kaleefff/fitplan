import Ionicons from '@expo/vector-icons/Ionicons';
import { StyleSheet, View } from 'react-native';

import type { IconName } from '@/constants/modules';
import { useAppTheme } from '@/hooks/use-app-theme';
import type { ColorName } from '@/theme/tokens';

type ModuleIconProps = {
  icon: IconName;
  color: ColorName;
  size?: number;
};

// Coloured rounded square with a white icon, as on the mockup tiles
export function ModuleIcon({ icon, color, size = 48 }: ModuleIconProps) {
  const { colors, radius, scheme } = useAppTheme();
  return (
    <View
      style={[
        styles.box,
        { width: size, height: size, borderRadius: radius.md, backgroundColor: colors[color] },
      ]}>
      <Ionicons
        name={icon}
        size={size * 0.5}
        // Dark mode uses light hues, so the icon is dark there for contrast
        color={scheme === 'dark' ? colors.background : '#FFFFFF'}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  box: { alignItems: 'center', justifyContent: 'center' },
});
