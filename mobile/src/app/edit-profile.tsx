import { router } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { fieldErrors, toApiError, userMessage } from '@/api/errors';
import type { components } from '@/api/schema';
import { useSession } from '@/auth/session';
import { checkName } from '@/auth/validation';
import { AppText } from '@/components/app-text';
import { Button } from '@/components/button';
import { Card } from '@/components/card';
import { Dialog } from '@/components/dialog';
import { FormMessage } from '@/components/form-message';
import { MultiOptionGroup, OptionGroup } from '@/components/option-group';
import { Screen } from '@/components/screen';
import { TextField } from '@/components/text-field';
import { useAppTheme } from '@/hooks/use-app-theme';
import { InjuryEditor } from '@/profile/health-step';
import {
  capitalize,
  EQUIPMENT_OPTIONS,
  GOAL_OPTIONS,
  injuryDurationLabel,
  labelOf,
  LEVEL_OPTIONS,
  PAL_OPTIONS,
  SEVERITY_OPTIONS,
  SEX_OPTIONS,
} from '@/profile/options';
import { PalHelp } from '@/profile/pal-help';
import {
  addInjury,
  deleteInjury,
  getAllergies,
  getInjuries,
  loadReferenceLists,
  saveAllergies,
  saveProfile,
  updateInjury,
  updateUser,
  type ReferenceLists,
} from '@/profile/profile-api';
import { profileToForm, toProfileInput, validateProfile, type ProfileForm } from '@/profile/validation';
import { readInsufficientExercises } from '@/training/insufficient';
import { generatePlan, getActivePlan, settingsOf, type TrainingPlan } from '@/training/training-api';

type Schemas = components['schemas'];
type Injury = Schemas['Injury'];
type InjuryInput = Schemas['InjuryInput'];
/** What happens to a saved injury when the user presses Save */
type InjuryChange = 'healed' | 'removed';

const PROFILE_FIELDS: (keyof ProfileForm)[] = [
  'age',
  'sex',
  'current_weight',
  'height',
  'activity_level_pal',
  'goal',
  'target_value',
  'experience_level',
  'equipment',
];

const sameIds = (a: number[], b: number[]) => [...a].sort().join() === [...b].sort().join();

type Health = { lists: ReferenceLists; injuries: Injury[]; allergenIds: number[] };

async function loadHealth(): Promise<Health> {
  const [lists, injuries, allergies] = await Promise.all([loadReferenceLists(), getInjuries(), getAllergies()]);
  return { lists, injuries, allergenIds: allergies.map((a) => a.id) };
}

type SavedInjuryProps = {
  injury: Injury;
  lists: ReferenceLists;
  change: InjuryChange | undefined;
  onChange: (change: InjuryChange | undefined) => void;
};

function SavedInjury({ injury, lists, change, onChange }: SavedInjuryProps) {
  const type = lists.injuryTypes?.find((t) => t.id === injury.injury_type_id)?.type_name ?? 'Injury';
  const group = capitalize(lists.muscleGroups?.find((g) => g.id === injury.affected_muscle_group_id)?.group_name ?? '');
  const details = [group, labelOf(SEVERITY_OPTIONS, injury.severity), injuryDurationLabel(injury.start_date)];
  if (!injury.is_active) {
    details.push('healed');
  }
  return (
    <Card style={styles.row}>
      <View style={styles.fill}>
        <AppText variant="bodyStrong">{type}</AppText>
        <AppText variant="caption" color="textMuted">
          {details.filter(Boolean).join(' · ')}
        </AppText>
        {change ? (
          <AppText variant="caption" color="primary">
            {change === 'healed' ? 'Marked as healed when you save' : 'Removed when you save'}
          </AppText>
        ) : null}
      </View>
      {change ? (
        <Button title="Undo" variant="ghost" onPress={() => onChange(undefined)} />
      ) : (
        <View>
          {injury.is_active ? (
            <Button title="Healed" variant="ghost" onPress={() => onChange('healed')} />
          ) : null}
          <Button title="Remove" variant="ghost" onPress={() => onChange('removed')} />
        </View>
      )}
    </Card>
  );
}

// Edit profile (M-08, FR-U6): name, biometric data, goal, training settings, allergies and injuries.
// When the injuries change and a training plan is active, the app offers a new plan (api-rules.md, Plans).
export default function EditProfileScreen() {
  const { spacing } = useAppTheme();
  const { user, profile, completeProfile, updateUser: setSessionUser } = useSession();
  const [names, setNames] = useState({ name: user?.name ?? '', surname: user?.surname ?? '' });
  const [form, setForm] = useState<ProfileForm>(() => profileToForm(profile!));
  const [health, setHealth] = useState<Health | null>(null);
  const [healthProblem, setHealthProblem] = useState<string | null>(null);
  const [allergenIds, setAllergenIds] = useState<number[]>([]);
  const [newInjuries, setNewInjuries] = useState<InjuryInput[]>([]);
  const [changes, setChanges] = useState<Record<number, InjuryChange>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ text: string; tone: 'error' | 'info' } | null>(null);
  const [busy, setBusy] = useState(false);
  /** The active plan to generate again; set when the injuries changed */
  const [planToRenew, setPlanToRenew] = useState<TrainingPlan | null>(null);
  const [generating, setGenerating] = useState(false);

  const showHealth = useCallback((loaded: Health) => {
    setHealth(loaded);
    setAllergenIds(loaded.allergenIds);
    setHealthProblem(null);
  }, []);
  const showHealthProblem = useCallback((error: unknown) => {
    setHealthProblem(`Your injuries and allergies could not be loaded. ${userMessage(toApiError(error))}`);
  }, []);

  useEffect(() => {
    let active = true;
    loadHealth()
      .then((loaded) => active && showHealth(loaded))
      .catch((error) => active && showHealthProblem(error));
    return () => {
      active = false;
    };
  }, [showHealth, showHealthProblem]);

  const reloadHealth = () => loadHealth().then(showHealth, showHealthProblem);

  function set<K extends keyof ProfileForm>(field: K, value: ProfileForm[K]) {
    setForm((current) => ({ ...current, [field]: value }));
    setErrors(({ [field]: _removed, ...rest }) => rest);
  }

  async function save() {
    const found: Record<string, string> = validateProfile(form, PROFILE_FIELDS);
    if (user) {
      const nameError = checkName(names.name, 'first name');
      const surnameError = checkName(names.surname, 'last name');
      if (nameError) found.name = nameError;
      if (surnameError) found.surname = surnameError;
    }
    setErrors(found);
    if (Object.keys(found).length > 0) {
      setMessage({ text: 'Please correct the highlighted fields.', tone: 'error' });
      return;
    }

    setBusy(true);
    setMessage(null);
    let injuriesChanged = false;
    // What is not saved yet; after an error only the rest is sent again
    let pendingInjuries = newInjuries;
    let pendingChanges = Object.entries(changes);
    try {
      const name = names.name.trim();
      const surname = names.surname.trim();
      if (user && (name !== user.name || surname !== user.surname)) {
        setSessionUser(await updateUser({ name, surname }));
      }
      const input = toProfileInput(form);
      const saved = profile ? toProfileInput(profileToForm(profile)) : null;
      if (JSON.stringify(input) !== JSON.stringify(saved)) {
        completeProfile(await saveProfile(input));
      }
      while (pendingInjuries.length > 0) {
        await addInjury(pendingInjuries[0]);
        pendingInjuries = pendingInjuries.slice(1);
        injuriesChanged = true;
      }
      while (pendingChanges.length > 0) {
        const [id, change] = pendingChanges[0];
        await (change === 'healed' ? updateInjury(Number(id), { is_active: false }) : deleteInjury(Number(id)));
        pendingChanges = pendingChanges.slice(1);
        injuriesChanged = true;
      }
      if (health && !sameIds(allergenIds, health.allergenIds)) {
        await saveAllergies(allergenIds);
      }
      setMessage({ text: 'Your profile is saved.', tone: 'info' });
    } catch (error) {
      const apiError = toApiError(error);
      if (apiError.code === 'validation_error') {
        setErrors(fieldErrors(apiError));
        setMessage({ text: 'Please correct the highlighted fields.', tone: 'error' });
      } else {
        setMessage({ text: userMessage(apiError), tone: 'error' });
      }
    } finally {
      setNewInjuries(pendingInjuries);
      setChanges(Object.fromEntries(pendingChanges));
      // What was saved before an error is shown as saved
      await reloadHealth();
      setBusy(false);
    }
    if (injuriesChanged) {
      setPlanToRenew(await getActivePlan().catch(() => null));
    }
  }

  async function renewPlan(plan: TrainingPlan) {
    setGenerating(true);
    try {
      await generatePlan(settingsOf(plan));
      setPlanToRenew(null);
      router.navigate('/training');
    } catch (error) {
      const apiError = toApiError(error);
      setPlanToRenew(null);
      setMessage({
        text: readInsufficientExercises(apiError)
          ? 'A new plan could not be generated with your current settings. Open Training to choose other settings.'
          : userMessage(apiError),
        tone: 'error',
      });
    } finally {
      setGenerating(false);
    }
  }

  return (
    <Screen>
      <FormMessage message={message?.text} tone={message?.tone} />

      {user ? (
        <Card style={{ gap: spacing.lg }}>
          <AppText variant="title">Name</AppText>
          <TextField
            label="First name"
            value={names.name}
            onChangeText={(name) => setNames({ ...names, name })}
            error={errors.name}
            autoComplete="given-name"
          />
          <TextField
            label="Last name"
            value={names.surname}
            onChangeText={(surname) => setNames({ ...names, surname })}
            error={errors.surname}
            autoComplete="family-name"
          />
        </Card>
      ) : null}

      <Card style={{ gap: spacing.lg }}>
        <AppText variant="title">About you</AppText>
        <TextField
          label="Age"
          value={form.age}
          onChangeText={(v) => set('age', v)}
          error={errors.age}
          keyboardType="number-pad"
          unit="years"
        />
        <OptionGroup label="Sex" options={SEX_OPTIONS} value={form.sex} onChange={(v) => set('sex', v)} error={errors.sex} />
        <TextField
          label="Weight"
          value={form.current_weight}
          onChangeText={(v) => set('current_weight', v)}
          error={errors.current_weight}
          keyboardType="decimal-pad"
          unit="kg"
        />
        <TextField
          label="Height"
          value={form.height}
          onChangeText={(v) => set('height', v)}
          error={errors.height}
          keyboardType="number-pad"
          unit="cm"
        />
      </Card>

      <Card style={{ gap: spacing.lg }}>
        <AppText variant="title">Activity and goal</AppText>
        <OptionGroup
          label="Activity level"
          options={PAL_OPTIONS}
          value={form.activity_level_pal}
          onChange={(v) => set('activity_level_pal', v)}
          error={errors.activity_level_pal}
          help={<PalHelp />}
        />
        <OptionGroup label="Goal" options={GOAL_OPTIONS} value={form.goal} onChange={(v) => set('goal', v)} error={errors.goal} />
        <TextField
          label="Target weight (optional)"
          value={form.target_value}
          onChangeText={(v) => set('target_value', v)}
          error={errors.target_value}
          helper="Used to estimate when you will reach your goal"
          keyboardType="decimal-pad"
          unit="kg"
        />
      </Card>

      <Card style={{ gap: spacing.lg }}>
        <AppText variant="title">Training</AppText>
        <OptionGroup
          label="Training experience"
          options={LEVEL_OPTIONS}
          value={form.experience_level}
          onChange={(v) => set('experience_level', v)}
          error={errors.experience_level}
        />
        <OptionGroup
          label="Available equipment"
          options={EQUIPMENT_OPTIONS}
          value={form.equipment}
          onChange={(v) => set('equipment', v)}
          error={errors.equipment}
        />
      </Card>

      <Card style={{ gap: spacing.lg }}>
        <AppText variant="title">Health</AppText>
        {healthProblem ? <FormMessage message={healthProblem} /> : null}
        {!health && !healthProblem ? <ActivityIndicator accessibilityLabel="Loading injuries and allergies" /> : null}
        {health ? (
          <>
            {health.lists.allergens ? (
              <MultiOptionGroup
                label="Allergies and intolerances"
                options={health.lists.allergens.map((a) => ({ value: a.id, label: a.name }))}
                values={allergenIds}
                onChange={setAllergenIds}
              />
            ) : null}
            <View style={{ gap: spacing.md }}>
              <AppText variant="bodyStrong">Your injuries</AppText>
              {health.injuries.length === 0 ? <AppText color="textMuted">No injuries saved.</AppText> : null}
              {health.injuries.map((injury) => (
                <SavedInjury
                  key={injury.id}
                  injury={injury}
                  lists={health.lists}
                  change={changes[injury.id]}
                  onChange={(change) =>
                    setChanges(({ [injury.id]: _removed, ...rest }) => (change ? { ...rest, [injury.id]: change } : rest))
                  }
                />
              ))}
            </View>
            <InjuryEditor
              title="New injuries"
              lists={health.lists}
              injuries={newInjuries}
              onInjuriesChange={setNewInjuries}
            />
          </>
        ) : null}
      </Card>

      <Button title="Save changes" onPress={save} loading={busy} />

      <Dialog
        visible={planToRenew !== null}
        title="Your injuries changed. Generate a new plan?"
        onClose={() => setPlanToRenew(null)}
        footer={
          <View style={{ gap: spacing.sm }}>
            <Button title="Generate new plan" onPress={() => renewPlan(planToRenew!)} loading={generating} />
            <Button title="Not now" variant="ghost" onPress={() => setPlanToRenew(null)} />
          </View>
        }>
        <AppText>
          The new plan uses the goal, days, level and equipment of your current plan. Your current plan stays until you
          accept the new one.
        </AppText>
      </Dialog>
    </Screen>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center' },
  fill: { flex: 1 },
});
