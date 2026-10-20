import { StyleSheet, View } from 'react-native';

import { AppText } from '@/components/app-text';
import { Card } from '@/components/card';
import { ModuleIcon } from '@/components/module-icon';
import { Screen } from '@/components/screen';
import { getModule, type ModuleKey } from '@/constants/modules';
import { useAppTheme } from '@/hooks/use-app-theme';

type PlaceholderScreenProps = {
  module: ModuleKey;
  upcoming: string[];
};

export function PlaceholderScreen({ module, upcoming }: PlaceholderScreenProps) {
  const { title, description, icon, color, tint } = getModule(module);
  const { colors, spacing } = useAppTheme();

  return (
    <Screen>
      <Card style={[styles.header, { gap: spacing.lg }]}>
        <ModuleIcon icon={icon} color={color} size={56} />
        <View style={styles.headerText}>
          <AppText variant="headline">{title}</AppText>
          <AppText color="textMuted">{description}</AppText>
        </View>
      </Card>

      <Card style={{ backgroundColor: colors[tint], borderColor: colors[tint] }}>
        <AppText variant="title">Coming soon</AppText>
        {upcoming.map((item) => (
          <AppText key={item}>• {item}</AppText>
        ))}
      </Card>
    </Screen>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: 'row', alignItems: 'center' },
  headerText: { flex: 1, gap: 2 },
});
