import { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';

import { AppText } from '@/components/app-text';
import { Button } from '@/components/button';
import { Dialog } from '@/components/dialog';
import { FormMessage } from '@/components/form-message';
import { TextField } from '@/components/text-field';
import type { FoodItem } from '@/diet/diet-api';
import { MIN_SEARCH, useFoodSearch } from '@/diet/use-food-search';
import { useAppTheme } from '@/hooks/use-app-theme';
import { minTouchSize } from '@/theme/tokens';
import { checkGrams } from '@/scanner/review-form';

type FoodPickerProps = {
  title: string;
  /** Also asks for the grams, starting at the food's usual portion (adding a product) */
  askGrams: boolean;
  busy: boolean;
  onPick: (food: FoodItem, grams: number | null) => void;
  onClose: () => void;
};

function FoodRow({ food, selected, onPress }: { food: FoodItem; selected: boolean; onPress: () => void }) {
  const { colors, radius, spacing } = useAppTheme();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected }}
      accessibilityLabel={`${food.name}, ${food.cals_per_100g} kcal per 100 g`}
      onPress={onPress}
      style={({ pressed }) => [
        styles.row,
        {
          borderRadius: radius.md,
          borderColor: selected ? colors.primary : colors.border,
          padding: spacing.sm,
          opacity: pressed ? 0.7 : 1,
        },
      ]}>
      <AppText>{food.name}</AppText>
      <AppText variant="caption" color="textMuted">
        {food.cals_per_100g} kcal per 100 g
      </AppText>
    </Pressable>
  );
}

/** Food database search to replace or add a product of a scan (FR-N4) */
export function FoodPicker({ title, askGrams, busy, onPick, onClose }: FoodPickerProps) {
  const { spacing } = useAppTheme();
  const [text, setText] = useState('');
  const search = useFoodSearch(text);
  const [chosen, setChosen] = useState<FoodItem | null>(null);
  const [grams, setGrams] = useState('');
  const [error, setError] = useState<string | undefined>(undefined);

  function choose(food: FoodItem) {
    if (!askGrams) {
      onPick(food, null);
      return;
    }
    setChosen(food);
    setGrams(String(food.default_portion_g));
    setError(undefined);
  }

  function add() {
    const problem = checkGrams(grams);
    setError(problem ?? undefined);
    if (!problem && chosen) {
      onPick(chosen, Number(grams.trim().replace(',', '.')));
    }
  }

  return (
    <Dialog
      visible
      title={title}
      onClose={onClose}
      footer={
        <View style={{ gap: spacing.sm, marginTop: spacing.md }}>
          {chosen ? <Button title={`Add ${chosen.name}`} onPress={add} loading={busy} /> : null}
          <Button title="Cancel" variant="ghost" onPress={onClose} disabled={busy} />
        </View>
      }>
      <TextField
        label="Find a food"
        value={text}
        onChangeText={setText}
        placeholder="For example: rice"
        autoCorrect={false}
        helper={`Type at least ${MIN_SEARCH} letters.`}
      />
      {chosen ? (
        <TextField
          label={`Grams of ${chosen.name}`}
          unit="g"
          value={grams}
          onChangeText={(value) => {
            setGrams(value);
            setError(undefined);
          }}
          error={error}
          keyboardType="decimal-pad"
        />
      ) : null}
      {busy && !askGrams ? <ActivityIndicator accessibilityLabel="Saving" /> : null}
      {search.status === 'loading' ? <ActivityIndicator accessibilityLabel="Searching foods" /> : null}
      {search.status === 'error' ? <FormMessage message={search.message} /> : null}
      {search.status === 'ready' && search.items.length === 0 ? (
        <AppText color="textMuted">No food found.</AppText>
      ) : null}
      {search.status === 'ready'
        ? search.items.map((food) => (
            <FoodRow
              key={food.id}
              food={food}
              selected={chosen?.id === food.id}
              onPress={() => !busy && choose(food)}
            />
          ))
        : null}
    </Dialog>
  );
}

const styles = StyleSheet.create({
  row: { minHeight: minTouchSize, borderWidth: 1, justifyContent: 'center' },
});
