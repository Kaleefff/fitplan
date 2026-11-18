import Ionicons from '@expo/vector-icons/Ionicons';
import { Image } from 'expo-image';
import { useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { toApiError, type ApiError } from '@/api/errors';
import { AppText } from '@/components/app-text';
import { Button } from '@/components/button';
import { Card } from '@/components/card';
import { Dialog } from '@/components/dialog';
import { FormMessage } from '@/components/form-message';
import { OptionGroup } from '@/components/option-group';
import { TextField } from '@/components/text-field';
import type { FoodItem } from '@/diet/diet-api';
import { useAppTheme } from '@/hooks/use-app-theme';
import { minTouchSize } from '@/theme/tokens';
import { FoodPicker } from '@/scanner/food-picker';
import { allergyItems, checkGrams, itemFlags, itemName, parseGrams } from '@/scanner/review-form';
import {
  addItem,
  amount,
  confirmProblem,
  confirmRecognition,
  deleteItem,
  discardRecognition,
  MEAL_TYPE_OPTIONS,
  percent,
  scanErrorMessage,
  updateItem,
  type NutritionLog,
  type Recognition,
  type RecognisedItem,
} from '@/scanner/scanner-api';

const HUNGER_OPTIONS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((value) => ({ value, label: String(value) }));

const FLAG_TEXT = {
  pick: { icon: 'help-circle-outline', text: 'Pick a food', color: 'warning' },
  allergen: { icon: 'alert-circle-outline', text: 'Contains your allergen', color: 'danger' },
  unsure: { icon: 'eye-outline', text: 'Not sure, check it', color: 'warning' },
} as const;

function Flag({ kind }: { kind: keyof typeof FLAG_TEXT }) {
  const { colors, spacing } = useAppTheme();
  const flag = FLAG_TEXT[kind];
  return (
    <View style={[styles.flag, { gap: spacing.xs }]}>
      <Ionicons name={flag.icon} size={16} color={colors[flag.color]} />
      <AppText variant="caption" color={flag.color}>
        {flag.text}
      </AppText>
    </View>
  );
}

function ItemRow({ item, onPress }: { item: RecognisedItem; onPress: () => void }) {
  const { colors, spacing } = useAppTheme();
  const flags = itemFlags(item);
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={[
        itemName(item),
        `${amount(item.grams)} grams`,
        `${amount(item.nutrition.kcal)} kcal`,
        ...flags.map((f) => FLAG_TEXT[f].text),
      ].join(', ')}
      accessibilityHint="Change the grams or the food, or remove it"
      onPress={onPress}
      style={({ pressed }) => [styles.item, { gap: spacing.sm, opacity: pressed ? 0.7 : 1 }]}>
      <View style={[styles.fill, { gap: 2 }]}>
        <AppText variant="bodyStrong">{itemName(item)}</AppText>
        <AppText variant="caption" color="textMuted">
          {amount(item.grams)} g · {amount(item.nutrition.kcal)} kcal · confidence {percent(item.confidence)}
        </AppText>
        {flags.map((flag) => (
          <Flag key={flag} kind={flag} />
        ))}
      </View>
      <Ionicons name="create-outline" size={22} color={colors.primary} />
    </Pressable>
  );
}

type ItemDialogProps = {
  item: RecognisedItem;
  busy: boolean;
  onSaveGrams: (grams: number) => void;
  onChangeFood: () => void;
  onRemove: () => void;
  onClose: () => void;
};

function ItemDialog({ item, busy, onSaveGrams, onChangeFood, onRemove, onClose }: ItemDialogProps) {
  const { spacing } = useAppTheme();
  const [grams, setGrams] = useState(item.grams > 0 ? amount(item.grams) : '');
  const [error, setError] = useState<string | undefined>(undefined);
  const unmatched = item.food_item_id === null;

  function save() {
    const problem = checkGrams(grams);
    setError(problem ?? undefined);
    if (!problem) {
      onSaveGrams(parseGrams(grams));
    }
  }

  return (
    <Dialog
      visible
      title={itemName(item)}
      onClose={onClose}
      footer={
        <View style={{ gap: spacing.sm, marginTop: spacing.md }}>
          {!unmatched ? <Button title="Save grams" onPress={save} loading={busy} /> : null}
          <Button
            title={unmatched ? 'Pick a food' : 'Change food'}
            variant={unmatched ? 'primary' : 'secondary'}
            onPress={onChangeFood}
            disabled={busy}
          />
          <Button title="Remove" variant="danger" onPress={onRemove} disabled={busy} />
          <Button title="Cancel" variant="ghost" onPress={onClose} disabled={busy} />
        </View>
      }>
      {unmatched ? (
        <AppText color="textMuted">
          This product is not in our food database. Pick the food it is, then set the grams.
        </AppText>
      ) : (
        <>
          <AppText color="textMuted">
            {amount(item.nutrition.kcal)} kcal · protein {amount(item.nutrition.protein)} g · fat{' '}
            {amount(item.nutrition.fat)} g · carbs {amount(item.nutrition.carbs)} g
          </AppText>
          <TextField
            label="Grams"
            unit="g"
            value={grams}
            onChangeText={(value) => {
              setGrams(value);
              setError(undefined);
            }}
            error={error}
            keyboardType="decimal-pad"
          />
        </>
      )}
    </Dialog>
  );
}

type Editing = { kind: 'item'; index: number } | { kind: 'replace'; index: number } | { kind: 'add' } | null;

type ReviewProps = {
  recognition: Recognition;
  /** Local preview of the photo; absent when a scan is resumed after a restart */
  photoUri: string | null;
  onChange: (recognition: Recognition) => void;
  onSaved: (log: NutritionLog) => void;
  onDiscarded: () => void;
  /** The scan expired (404): start again */
  onExpired: (message: string) => void;
};

// Review of FR-N4: correct the products and grams, see allergy warnings, then confirm or discard
export function Review({ recognition, photoUri, onChange, onSaved, onDiscarded, onExpired }: ReviewProps) {
  const { colors, spacing } = useAppTheme();
  const [editing, setEditing] = useState<Editing>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [hungerBefore, setHungerBefore] = useState<number | null>(null);
  const [hungerAfter, setHungerAfter] = useState<number | null>(null);

  const totals = recognition.totals;
  const allergies = allergyItems(recognition);
  const problem = confirmProblem(recognition);

  async function run<T>(call: () => Promise<T>, done: (value: T) => void) {
    setBusy(true);
    setMessage(null);
    try {
      done(await call());
    } catch (error) {
      const apiError: ApiError = toApiError(error);
      // A message under an open window would stay hidden, so the window closes
      setEditing(null);
      if (apiError.status === 404) {
        onExpired(scanErrorMessage(apiError));
        return;
      }
      setMessage(scanErrorMessage(apiError));
    } finally {
      setBusy(false);
    }
  }

  const changed = (next: Recognition) => {
    setEditing(null);
    onChange(next);
  };

  function pick(food: FoodItem, grams: number | null) {
    if (editing?.kind === 'add') {
      run(() => addItem(recognition.id, food.id, grams ?? food.default_portion_g), changed);
    } else if (editing?.kind === 'replace') {
      const item = recognition.recognised_items[editing.index];
      // An unmatched item has no grams yet; the food's usual portion is a start the user can correct
      const change =
        item.grams > 0 ? { food_item_id: food.id } : { food_item_id: food.id, grams: food.default_portion_g };
      run(() => updateItem(recognition.id, editing.index, change), changed);
    }
  }

  function save() {
    if (problem) {
      setMessage(problem);
      return;
    }
    run(
      () =>
        confirmRecognition(recognition.id, {
          hunger_level_before: hungerBefore,
          hunger_level_after: hungerAfter,
        }),
      onSaved,
    );
  }

  const editedItem = editing?.kind === 'item' ? recognition.recognised_items[editing.index] : null;

  return (
    <>
      <Card>
        {photoUri ? (
          <Image
            source={{ uri: photoUri }}
            style={[styles.photo, { borderRadius: spacing.sm }]}
            contentFit="cover"
            accessibilityLabel="Your meal photo"
          />
        ) : null}
        <AppText variant="title">
          {MEAL_TYPE_OPTIONS.find((o) => o.value === recognition.meal_type)?.label ?? recognition.meal_type}
        </AppText>
        <AppText color="textMuted">
          Recognised by AI with up to {percent(recognition.overall_confidence)} confidence. Check every product and its
          grams before saving.
        </AppText>
      </Card>

      {allergies.length > 0 ? (
        <Card style={{ borderColor: colors.danger, borderLeftWidth: 4 }} accessibilityRole="alert">
          <View style={[styles.flag, { gap: spacing.sm }]}>
            <Ionicons name="alert-circle" size={22} color={colors.danger} />
            <AppText variant="bodyStrong">Allergy warning</AppText>
          </View>
          <AppText>
            {allergies.join(', ')} {allergies.length === 1 ? 'contains' : 'contain'} one of your allergens. Remove it or
            change the food if this is wrong.
          </AppText>
        </Card>
      ) : null}

      <Card>
        <AppText variant="caption" color="textMuted">
          This meal
        </AppText>
        <AppText variant="title" accessibilityLabel={`${amount(totals?.kcal ?? 0)} kcal`}>
          {amount(totals?.kcal ?? 0)} kcal
        </AppText>
        <AppText color="textMuted">
          Protein {amount(totals?.protein ?? 0)} g · Fat {amount(totals?.fat ?? 0)} g · Carbs{' '}
          {amount(totals?.carbs ?? 0)} g
        </AppText>
      </Card>

      <Card style={{ gap: spacing.sm }}>
        <AppText variant="title">Products</AppText>
        {recognition.recognised_items.length === 0 ? (
          <AppText color="textMuted">No product was recognised. Add what you ate.</AppText>
        ) : null}
        {recognition.recognised_items.map((item, index) => (
          <ItemRow key={`${index}-${item.name}`} item={item} onPress={() => setEditing({ kind: 'item', index })} />
        ))}
        <Button title="Add a product" variant="secondary" onPress={() => setEditing({ kind: 'add' })} />
      </Card>

      <Card style={{ gap: spacing.md }}>
        <AppText variant="title">Hunger (optional)</AppText>
        <OptionGroup
          label="Before the meal"
          options={HUNGER_OPTIONS}
          value={hungerBefore}
          onChange={(value) => setHungerBefore(value === hungerBefore ? null : value)}
        />
        <OptionGroup
          label="After the meal"
          options={HUNGER_OPTIONS}
          value={hungerAfter}
          onChange={(value) => setHungerAfter(value === hungerAfter ? null : value)}
        />
        <AppText variant="caption" color="textMuted">
          1 = not hungry at all, 10 = very hungry.
        </AppText>
      </Card>

      <FormMessage message={message} />
      <Button title="Save meal" onPress={save} loading={busy && editing === null} />
      <Button
        title="Discard"
        variant="ghost"
        disabled={busy}
        onPress={() => run(() => discardRecognition(recognition.id), onDiscarded)}
      />

      {editedItem && editing?.kind === 'item' ? (
        <ItemDialog
          key={editing.index}
          item={editedItem}
          busy={busy}
          onSaveGrams={(grams) => run(() => updateItem(recognition.id, editing.index, { grams }), changed)}
          onChangeFood={() => setEditing({ kind: 'replace', index: editing.index })}
          onRemove={() => run(() => deleteItem(recognition.id, editing.index), changed)}
          onClose={() => setEditing(null)}
        />
      ) : null}
      {editing?.kind === 'replace' || editing?.kind === 'add' ? (
        <FoodPicker
          title={editing.kind === 'add' ? 'Add a product' : 'Pick the food'}
          askGrams={editing.kind === 'add'}
          busy={busy}
          onPick={pick}
          onClose={() => setEditing(null)}
        />
      ) : null}
    </>
  );
}

const styles = StyleSheet.create({
  photo: { width: '100%', height: 180 },
  item: { minHeight: minTouchSize, flexDirection: 'row', alignItems: 'center' },
  flag: { flexDirection: 'row', alignItems: 'center' },
  fill: { flex: 1 },
});
