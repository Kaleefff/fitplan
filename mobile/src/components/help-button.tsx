import Ionicons from '@expo/vector-icons/Ionicons';
import { useState, type ReactNode } from 'react';
import { Pressable } from 'react-native';

import { Button } from '@/components/button';
import { Dialog } from '@/components/dialog';
import { useAppTheme } from '@/hooks/use-app-theme';
import { minTouchSize } from '@/theme/tokens';

const ICON_SIZE = 20;

type HelpButtonProps = {
  /** Heading of the window; also what a screen reader says for the button */
  title: string;
  children: ReactNode;
};

/** "?" next to a label; opens a window that explains it */
export function HelpButton({ title, children }: HelpButtonProps) {
  const { colors } = useAppTheme();
  const [open, setOpen] = useState(false);
  const close = () => setOpen(false);

  return (
    <>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={title}
        onPress={() => setOpen(true)}
        // The icon stays small next to the label; the touch area keeps the minimum size
        hitSlop={(minTouchSize - ICON_SIZE) / 2}
        style={({ pressed }) => ({ opacity: pressed ? 0.7 : 1 })}>
        <Ionicons name="help-circle-outline" size={ICON_SIZE} color={colors.primary} />
      </Pressable>

      <Dialog visible={open} title={title} onClose={close} footer={<Button title="Got it" onPress={close} />}>
        {children}
      </Dialog>
    </>
  );
}
