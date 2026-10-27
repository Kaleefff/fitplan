import { Stack } from 'expo-router';

// Screens for signed-out users; the root layout shows this group only in that state
export default function AuthLayout() {
  return <Stack screenOptions={{ headerShown: false }} />;
}
