import Ionicons from '@expo/vector-icons/Ionicons';
import { Tabs } from 'expo-router/js-tabs';

import { HeaderSettingsButton } from '@/components/header-settings-button';
import { getModule, type IconName, type ModuleKey } from '@/constants/modules';
import { useAppTheme } from '@/hooks/use-app-theme';

// Same colours as the tab labels: primary when selected, muted otherwise
function TabIcon({ name, focused, size }: { name: IconName; focused: boolean; size: number }) {
  const { colors } = useAppTheme();
  return <Ionicons name={name} size={size} color={focused ? colors.primary : colors.textMuted} />;
}

function tabIcon(name: IconName) {
  return function TabBarIcon({ focused, size }: { focused: boolean; size: number }) {
    return <TabIcon name={name} focused={focused} size={size} />;
  };
}

// Tab label, header title and icon of a module tab come from MODULES
function moduleTab(key: ModuleKey) {
  const module = getModule(key);
  return { title: module.tabLabel, headerTitle: module.title, tabBarIcon: tabIcon(module.icon) };
}

// Bottom tab bar of the mockups: Home, Training, Scan, Diet, Stats
export default function TabsLayout() {
  const { colors } = useAppTheme();

  return (
    <Tabs
      screenOptions={{
        tabBarActiveTintColor: colors.primary,
        tabBarInactiveTintColor: colors.textMuted,
        headerRight: () => <HeaderSettingsButton />,
      }}>
      <Tabs.Screen
        name="index"
        options={{ title: 'Home', headerTitle: 'FitPlan Pro', tabBarIcon: tabIcon('home-outline') }}
      />
      <Tabs.Screen name="training" options={moduleTab('training')} />
      <Tabs.Screen name="scan" options={moduleTab('scan')} />
      <Tabs.Screen name="diet" options={moduleTab('diet')} />
      <Tabs.Screen name="stats" options={moduleTab('stats')} />
    </Tabs>
  );
}
