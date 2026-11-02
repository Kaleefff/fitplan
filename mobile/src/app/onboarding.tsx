import { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { fieldErrors, toApiError, userMessage } from '@/api/errors';
import type { components } from '@/api/schema';
import { useSession } from '@/auth/session';
import { Button } from '@/components/button';
import { FormMessage } from '@/components/form-message';
import { OptionGroup } from '@/components/option-group';
import { ProgressSteps } from '@/components/progress-steps';
import { Screen } from '@/components/screen';
import { TextField } from '@/components/text-field';
import { useAppTheme } from '@/hooks/use-app-theme';
import { HealthStep } from '@/profile/health-step';
import { EQUIPMENT_OPTIONS, GOAL_OPTIONS, LEVEL_OPTIONS, PAL_OPTIONS, SEX_OPTIONS } from '@/profile/options';
import { PalHelp } from '@/profile/pal-help';
import { addInjury, loadReferenceLists, saveAllergies, saveProfile, type ReferenceLists } from '@/profile/profile-api';
import { EMPTY_PROFILE_FORM, toProfileInput, validateProfile, type ProfileForm } from '@/profile/validation';

type Profile = components['schemas']['Profile'];
type InjuryInput = components['schemas']['InjuryInput'];

const STEPS: { title: string; fields: (keyof ProfileForm)[] }[] = [
  { title: 'About you', fields: ['age', 'sex', 'current_weight', 'height'] },
  { title: 'Activity and goal', fields: ['activity_level_pal', 'goal', 'target_value'] },
  { title: 'Training', fields: ['experience_level', 'equipment'] },
  { title: 'Health', fields: [] },
];
const ALL_FIELDS = STEPS.flatMap((step) => step.fields);

/** Index of the first step that contains one of the fields with an error */
function stepOf(errors: Record<string, string>): number {
  const index = STEPS.findIndex((step) => step.fields.some((field) => field in errors));
  return index === -1 ? 0 : index;
}

// "Set Up Your Profile" (Rys. 7.3, 7.4), FR-U6, FR-U7; shown until the user has a profile
export default function OnboardingScreen() {
  const { completeProfile, signOut } = useSession();
  const { spacing } = useAppTheme();
  const [step, setStep] = useState(0);
  const [form, setForm] = useState<ProfileForm>(EMPTY_PROFILE_FORM);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [lists, setLists] = useState<ReferenceLists | null>(null);
  const [allergenIds, setAllergenIds] = useState<number[]>([]);
  const [injuries, setInjuries] = useState<InjuryInput[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Set when the profile is saved but injuries or allergies were not: the user may still go on
  const [savedProfile, setSavedProfile] = useState<Profile | null>(null);

  useEffect(() => {
    loadReferenceLists().then(setLists);
  }, []);

  // Typing in or choosing for a field clears its error
  function set<K extends keyof ProfileForm>(field: K, value: ProfileForm[K]) {
    setForm((current) => ({ ...current, [field]: value }));
    setErrors(({ [field]: _removed, ...rest }) => rest);
  }

  function next() {
    const found = validateProfile(form, STEPS[step].fields);
    setErrors(found);
    if (Object.keys(found).length === 0) {
      setMessage(null);
      setStep(step + 1);
    }
  }

  async function finish() {
    const found = validateProfile(form, ALL_FIELDS);
    if (Object.keys(found).length > 0) {
      setErrors(found);
      setStep(stepOf(found));
      return;
    }
    setBusy(true);
    setMessage(null);

    let profile: Profile;
    try {
      profile = await saveProfile(toProfileInput(form));
    } catch (error) {
      const apiError = toApiError(error);
      if (apiError.code === 'validation_error') {
        const serverErrors = fieldErrors(apiError);
        setErrors(serverErrors);
        setStep(stepOf(serverErrors));
        setMessage('Please correct the highlighted fields.');
      } else if (apiError.status === 404 || apiError.status === 405) {
        setMessage('This server cannot save profiles yet. Try again when the backend supports it.');
      } else {
        setMessage(userMessage(apiError));
      }
      setBusy(false);
      return;
    }

    // The profile is what Home and the plans need; injuries and allergies can be added later too
    const failed: string[] = [];
    try {
      for (const injury of injuries) {
        await addInjury(injury);
      }
    } catch {
      failed.push('injuries');
    }
    if (allergenIds.length > 0) {
      await saveAllergies(allergenIds).catch(() => failed.push('allergies'));
    }

    if (failed.length === 0) {
      completeProfile(profile); // the router then opens Home
      return;
    }
    setSavedProfile(profile);
    setMessage(`Your profile is saved, but your ${failed.join(' and ')} could not be saved. You can add them later in Settings.`);
    setBusy(false);
  }

  const last = step === STEPS.length - 1;

  return (
    <Screen>
      <ProgressSteps current={step + 1} total={STEPS.length} title={STEPS[step].title} />
      <FormMessage message={message} tone={savedProfile ? 'info' : 'error'} />

      {step === 0 ? (
        <>
          <TextField
            label="Age"
            value={form.age}
            onChangeText={(v) => set('age', v)}
            error={errors.age}
            keyboardType="number-pad"
            unit="years"
            placeholder="25"
          />
          <OptionGroup
            label="Sex"
            options={SEX_OPTIONS}
            value={form.sex}
            onChange={(v) => set('sex', v)}
            error={errors.sex}
          />
          <TextField
            label="Weight"
            value={form.current_weight}
            onChangeText={(v) => set('current_weight', v)}
            error={errors.current_weight}
            keyboardType="decimal-pad"
            unit="kg"
            placeholder="70"
          />
          <TextField
            label="Height"
            value={form.height}
            onChangeText={(v) => set('height', v)}
            error={errors.height}
            keyboardType="number-pad"
            unit="cm"
            placeholder="175"
          />
        </>
      ) : null}

      {step === 1 ? (
        <>
          <OptionGroup
            label="Activity level"
            options={PAL_OPTIONS}
            value={form.activity_level_pal}
            onChange={(v) => set('activity_level_pal', v)}
            error={errors.activity_level_pal}
            help={<PalHelp />}
          />
          <OptionGroup
            label="Goal"
            options={GOAL_OPTIONS}
            value={form.goal}
            onChange={(v) => set('goal', v)}
            error={errors.goal}
          />
          <TextField
            label="Target weight (optional)"
            value={form.target_value}
            onChangeText={(v) => set('target_value', v)}
            error={errors.target_value}
            helper="Used to estimate when you will reach your goal"
            keyboardType="decimal-pad"
            unit="kg"
          />
        </>
      ) : null}

      {step === 2 ? (
        <>
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
        </>
      ) : null}

      {last ? (
        <HealthStep
          lists={lists}
          allergenIds={allergenIds}
          onAllergensChange={setAllergenIds}
          injuries={injuries}
          onInjuriesChange={setInjuries}
        />
      ) : null}

      <View style={[styles.buttons, { gap: spacing.md }]}>
        {step > 0 && !savedProfile ? (
          <Button title="Back" variant="secondary" onPress={() => setStep(step - 1)} style={styles.button} />
        ) : null}
        {savedProfile ? (
          <Button title="Continue to Home" onPress={() => completeProfile(savedProfile)} style={styles.button} />
        ) : (
          <Button
            title={last ? 'Finish' : 'Continue'}
            onPress={last ? finish : next}
            loading={busy}
            style={styles.button}
          />
        )}
      </View>
      <Button title="Sign out" variant="ghost" onPress={signOut} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  buttons: { flexDirection: 'row' },
  button: { flex: 1 },
});
