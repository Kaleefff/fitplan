import type { ReactNode } from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { AppText } from '@/components/app-text';
import { Card } from '@/components/card';
import { useAppTheme } from '@/hooks/use-app-theme';

type DialogProps = {
  visible: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  /** Stays under the scrolling content, for example a button */
  footer?: ReactNode;
};

/** Window over the screen; the system back button and a tap outside close it */
export function Dialog({ visible, title, onClose, children, footer }: DialogProps) {
  const { spacing } = useAppTheme();
  return (
    <Modal visible={visible} transparent animationType="fade" statusBarTranslucent onRequestClose={onClose}>
      <View style={[styles.center, { padding: spacing.lg }]}>
        <Pressable style={[StyleSheet.absoluteFill, styles.backdrop]} onPress={onClose} />
        <Card style={styles.window}>
          <AppText variant="title" accessibilityRole="header">
            {title}
          </AppText>
          <ScrollView contentContainerStyle={{ gap: spacing.md }}>{children}</ScrollView>
          {footer}
        </Card>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  backdrop: { backgroundColor: 'rgba(0, 0, 0, 0.5)' },
  window: { width: '100%', maxWidth: 420, maxHeight: '100%' },
});
