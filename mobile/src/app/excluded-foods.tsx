import Ionicons from '@expo/vector-icons/Ionicons';
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';

import { toApiError, userMessage } from '@/api/errors';
import { AppText } from '@/components/app-text';
import { Button } from '@/components/button';
import { Card } from '@/components/card';
import { FormMessage } from '@/components/form-message';
import { Screen } from '@/components/screen';
import { TextField } from '@/components/text-field';
import {
  dietSettingsOf,
  excludedInPlan,
  generateDietPlan,
  getActiveDietPlan,
  getDraftDietPlan,
  getExcludedFoods,
  getFood,
  saveExcludedFoods,
  searchFoods,
  type DietPlan,
  type FoodItem,
} from '@/diet/diet-api';
import { insufficientFoodsMessage } from '@/diet/diet-form';
import { useAppTheme } from '@/hooks/use-app-theme';
import { minTouchSize } from '@/theme/tokens';

/** Search starts from this many letters, a short wait after the last key */
const MIN_SEARCH = 2;
const SEARCH_DELAY_MS = 300;

function FoodRow({ food, checked, onToggle }: { food: FoodItem; checked: boolean; onToggle: () => void }) {
  const { colors, spacing } = useAppTheme();
  return (
    <Pressable
      accessibilityRole="checkbox"
      accessibilityState={{ checked }}
      accessibilityLabel={`Exclude ${food.name}`}
      onPress={onToggle}
      style={({ pressed }) => [styles.row, { gap: spacing.md, opacity: pressed ? 0.7 : 1 }]}>
      <View style={styles.fill}>
        <AppText>{food.name}</AppText>
        <AppText variant="caption" color="textMuted">
          {food.cals_per_100g} kcal per 100 g
        </AppText>
      </View>
      <Ionicons
        name={checked ? 'checkbox' : 'square-outline'}
        size={26}
        color={checked ? colors.primary : colors.textMuted}
      />
    </Pressable>
  );
}

type Search = { status: 'idle' } | { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; items: FoodItem[] };

/** Results of the last finished search; idle and loading follow from the text */
type Result = { query: string; items: FoodItem[] } | { query: string; error: string };

function useFoodSearch(text: string): Search {
  const [result, setResult] = useState<Result | null>(null);
  const query = text.trim();
  useEffect(() => {
    if (query.length < MIN_SEARCH) {
      return;
    }
    let current = true;
    const timer = setTimeout(() => {
      searchFoods(query)
        .then((items) => current && setResult({ query, items }))
        .catch((error) => current && setResult({ query, error: userMessage(toApiError(error)) }));
    }, SEARCH_DELAY_MS);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [query]);

  if (query.length < MIN_SEARCH) return { status: 'idle' };
  if (result?.query !== query) return { status: 'loading' };
  return 'error' in result ? { status: 'error', message: result.error } : { status: 'ready', items: result.items };
}

type Load = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; saved: FoodItem[] };
/** A diet plan that still has foods the user has just excluded */
type Offer = { plan: DietPlan; names: string[] };

const sameIds = (a: FoodItem[], b: FoodItem[]) =>
  a.length === b.length && a.every((food) => b.some((other) => other.id === food.id));

// Foods the user never wants in a diet plan (M-11, FR-P6, algorithms.md 5.2). They take effect when
// a plan is generated; the app offers to generate one when the current plan still has them (FR-P7).
export default function ExcludedFoodsScreen() {
  const { spacing } = useAppTheme();
  /** Id of a food to add at once, from a tap on a food of the diet plan */
  const { add } = useLocalSearchParams<{ add?: string }>();
  const [load, setLoad] = useState<Load>({ status: 'loading' });
  const [list, setList] = useState<FoodItem[]>([]);
  const [text, setText] = useState('');
  const search = useFoodSearch(text);
  const [message, setMessage] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [offer, setOffer] = useState<Offer | null>(null);
  const [generating, setGenerating] = useState(false);
  const [generated, setGenerated] = useState(false);

  useEffect(() => {
    let current = true;
    const addId = add ? Number(add) : null;
    Promise.all([getExcludedFoods(), addId ? getFood(addId) : Promise.resolve(null)])
      .then(([saved, extra]) => {
        if (!current) return;
        setLoad({ status: 'ready', saved });
        setList(extra && !saved.some((food) => food.id === extra.id) ? [...saved, extra] : saved);
      })
      .catch((error) => current && setLoad({ status: 'error', message: userMessage(toApiError(error)) }));
    return () => {
      current = false;
    };
  }, [add]);

  if (load.status === 'loading') {
    return (
      <Screen>
        <ActivityIndicator accessibilityLabel="Loading your excluded foods" />
      </Screen>
    );
  }
  if (load.status === 'error') {
    return (
      <Screen>
        <FormMessage message={load.message} />
        <Button title="Back" variant="secondary" onPress={() => router.back()} />
      </Screen>
    );
  }

  const changed = !sameIds(list, load.saved);
  const toggle = (food: FoodItem) => {
    setMessage(null);
    setNotice(null);
    setList((current) =>
      current.some((f) => f.id === food.id) ? current.filter((f) => f.id !== food.id) : [...current, food],
    );
  };

  async function save() {
    setSaving(true);
    setMessage(null);
    setNotice(null);
    setOffer(null);
    setGenerated(false);
    try {
      const saved = await saveExcludedFoods(list.map((food) => food.id));
      setLoad({ status: 'ready', saved });
      setList(saved);
      setNotice('Excluded foods saved. New diet plans leave them out.');
      // The newest plan the user looks at: the draft, else the active one
      const [active, draft] = await Promise.all([getActiveDietPlan(), getDraftDietPlan()]).catch(() => [null, null]);
      const plan = draft ?? active;
      const names = plan ? excludedInPlan(plan, saved.map((food) => food.id)) : [];
      setOffer(plan && names.length > 0 ? { plan, names } : null);
    } catch (error) {
      const apiError = toApiError(error);
      setMessage(
        apiError.status === 422
          ? 'One of these foods is no longer in the food database. Remove it and save again.'
          : userMessage(apiError),
      );
    } finally {
      setSaving(false);
    }
  }

  async function generate(plan: DietPlan) {
    setGenerating(true);
    setMessage(null);
    try {
      await generateDietPlan(dietSettingsOf(plan));
      setOffer(null);
      setGenerated(true);
    } catch (error) {
      const apiError = toApiError(error);
      setMessage(insufficientFoodsMessage(apiError) ?? userMessage(apiError));
    } finally {
      setGenerating(false);
    }
  }

  const listIds = new Set(list.map((food) => food.id));

  return (
    <Screen>
      <AppText color="textMuted">
        Foods you never want in a diet plan. Foods with your allergens are left out anyway.
      </AppText>
      <FormMessage message={notice} tone="info" />
      <FormMessage message={message} />

      {offer ? (
        <Card accessibilityRole="alert">
          <AppText variant="bodyStrong">
            Your {offer.plan.status === 'draft' ? 'draft' : 'current'} diet plan has foods you excluded
          </AppText>
          <AppText color="textMuted">{offer.names.join(', ')}. Generate a new plan without them?</AppText>
          <AppText variant="caption" color="textMuted">
            {offer.plan.status === 'active'
              ? 'It keeps the same settings. Your current plan stays until you accept the new one.'
              : 'It keeps the same settings and replaces this draft.'}
          </AppText>
          <Button title="Generate new plan" onPress={() => generate(offer.plan)} loading={generating} />
          <Button title="Not now" variant="ghost" onPress={() => setOffer(null)} disabled={generating} />
        </Card>
      ) : null}
      {generated ? (
        <Card>
          <AppText variant="bodyStrong">A new draft is ready</AppText>
          <AppText color="textMuted">Review it and accept it on the Diet tab.</AppText>
          <Button title="Open the Diet tab" onPress={() => router.navigate('/diet')} />
        </Card>
      ) : null}

      <Card>
        <AppText variant="title">Your excluded foods</AppText>
        {list.length === 0 ? <AppText color="textMuted">No foods excluded.</AppText> : null}
        {list.map((food) => (
          <FoodRow key={food.id} food={food} checked onToggle={() => toggle(food)} />
        ))}
        <Button title="Save" onPress={save} loading={saving} disabled={!changed} />
      </Card>

      <Card style={{ gap: spacing.md }}>
        <TextField
          label="Find a food"
          value={text}
          onChangeText={setText}
          placeholder="For example: broccoli"
          autoCorrect={false}
          helper={`Type at least ${MIN_SEARCH} letters.`}
        />
        {search.status === 'loading' ? <ActivityIndicator accessibilityLabel="Searching foods" /> : null}
        {search.status === 'error' ? <FormMessage message={search.message} /> : null}
        {search.status === 'ready' && search.items.length === 0 ? (
          <AppText color="textMuted">No food found.</AppText>
        ) : null}
        {search.status === 'ready'
          ? search.items.map((food) => (
              <FoodRow key={food.id} food={food} checked={listIds.has(food.id)} onToggle={() => toggle(food)} />
            ))
          : null}
      </Card>
    </Screen>
  );
}

const styles = StyleSheet.create({
  row: { minHeight: minTouchSize, flexDirection: 'row', alignItems: 'center' },
  fill: { flex: 1 },
});
