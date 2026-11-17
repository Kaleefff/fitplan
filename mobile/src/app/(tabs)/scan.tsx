import Ionicons from '@expo/vector-icons/Ionicons';
import { Image } from 'expo-image';
import * as ImagePicker from 'expo-image-picker';
import { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { toApiError } from '@/api/errors';
import { AppText } from '@/components/app-text';
import { Button } from '@/components/button';
import { Card } from '@/components/card';
import { FormMessage } from '@/components/form-message';
import { OptionGroup } from '@/components/option-group';
import { Screen } from '@/components/screen';
import { useAppTheme } from '@/hooks/use-app-theme';
import { Review } from '@/scanner/review';
import {
  amount,
  defaultMealType,
  MEAL_TYPE_OPTIONS,
  pendingScan,
  photoProblem,
  resumePendingScan,
  scanErrorMessage,
  SLOW_AFTER_MS,
  UploadCancelled,
  uploadPhoto,
  type MealType,
  type NutritionLog,
  type Photo,
  type Recognition,
} from '@/scanner/scanner-api';

type Step =
  | { kind: 'checking' }
  | { kind: 'start' }
  | { kind: 'uploading'; photo: Photo; progress: number; slow: boolean }
  | { kind: 'failed'; photo: Photo; message: string }
  | { kind: 'review'; recognition: Recognition; photoUri: string | null }
  | { kind: 'saved'; log: NutritionLog };

/** The picked file as the upload needs it; the type falls back to the file name, then to JPEG */
function toPhoto(asset: ImagePicker.ImagePickerAsset): Photo {
  const extension = (asset.fileName ?? asset.uri).split('.').pop()?.toLowerCase();
  const fromName = extension === 'png' ? 'image/png' : extension === 'webp' ? 'image/webp' : 'image/jpeg';
  const mimeType = asset.mimeType ?? fromName;
  return {
    uri: asset.uri,
    mimeType,
    fileName: asset.fileName ?? `meal.${mimeType.split('/')[1]}`,
    fileSize: asset.fileSize ?? null,
  };
}

function ProgressBar({ fraction }: { fraction: number }) {
  const { colors, radius } = useAppTheme();
  const value = Math.round(fraction * 100);
  return (
    <View
      accessibilityRole="progressbar"
      accessibilityLabel="Upload"
      accessibilityValue={{ min: 0, max: 100, now: value }}
      style={[styles.track, { backgroundColor: colors.surfaceAlt, borderRadius: radius.md }]}>
      <View style={[styles.bar, { width: `${value}%`, backgroundColor: colors.scanner, borderRadius: radius.md }]} />
    </View>
  );
}

// AI Food Scanner (M-15, FR-N1–N4): photo, upload with progress, review and corrections, confirm or discard
export default function ScanScreen() {
  const { colors, spacing } = useAppTheme();
  const [step, setStep] = useState<Step>({ kind: 'checking' });
  const [mealType, setMealType] = useState<MealType>(() => defaultMealType());
  const [message, setMessage] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const cancelUpload = useRef<(() => void) | null>(null);

  // A scan under review survives an app restart until it expires (6 h)
  useEffect(() => {
    let current = true;
    resumePendingScan()
      .then((recognition) => {
        if (current) setStep(recognition ? { kind: 'review', recognition, photoUri: null } : { kind: 'start' });
      })
      .catch(() => current && setStep({ kind: 'start' }));
    return () => {
      current = false;
      cancelUpload.current?.();
    };
  }, []);

  async function send(photo: Photo) {
    setMessage(null);
    setNotice(null);
    setStep({ kind: 'uploading', photo, progress: 0, slow: false });
    const upload = uploadPhoto(photo, mealType, (progress) =>
      setStep((now) => (now.kind === 'uploading' ? { ...now, progress } : now)),
    );
    cancelUpload.current = upload.cancel;
    const slowTimer = setTimeout(
      () => setStep((now) => (now.kind === 'uploading' ? { ...now, slow: true } : now)),
      SLOW_AFTER_MS,
    );
    try {
      const recognition = await upload.promise;
      await pendingScan.set(recognition.id);
      setStep({ kind: 'review', recognition, photoUri: photo.uri });
    } catch (error) {
      setStep(
        error instanceof UploadCancelled
          ? { kind: 'start' }
          : { kind: 'failed', photo, message: scanErrorMessage(toApiError(error)) },
      );
    } finally {
      clearTimeout(slowTimer);
      cancelUpload.current = null;
    }
  }

  async function pick(source: 'camera' | 'gallery') {
    setMessage(null);
    setNotice(null);
    try {
      if (source === 'camera') {
        const permission = await ImagePicker.requestCameraPermissionsAsync();
        if (!permission.granted) {
          setMessage('Allow camera access in the system settings, or choose a photo from the gallery.');
          return;
        }
      }
      const options: ImagePicker.ImagePickerOptions = { mediaTypes: ['images'], quality: 0.7 };
      const result =
        source === 'camera'
          ? await ImagePicker.launchCameraAsync(options)
          : await ImagePicker.launchImageLibraryAsync(options);
      if (result.canceled || result.assets.length === 0) {
        return;
      }
      const photo = toPhoto(result.assets[0]);
      const problem = photoProblem(photo);
      if (problem) {
        setMessage(problem);
        return;
      }
      await send(photo);
    } catch {
      setMessage('The camera or the gallery could not be opened. Try again.');
    }
  }

  async function finish(next: Step, text: { error?: string; info?: string } = {}) {
    await pendingScan.clear();
    setMessage(text.error ?? null);
    setNotice(text.info ?? null);
    setStep(next);
  }

  if (step.kind === 'checking') {
    return (
      <Screen>
        <ActivityIndicator accessibilityLabel="Loading the scanner" />
      </Screen>
    );
  }

  if (step.kind === 'review') {
    return (
      <Screen>
        <Review
          recognition={step.recognition}
          photoUri={step.photoUri}
          onChange={(recognition) => setStep({ ...step, recognition })}
          onSaved={(log) => finish({ kind: 'saved', log })}
          onDiscarded={() => finish({ kind: 'start' }, { info: 'The scan was discarded.' })}
          onExpired={(error) => finish({ kind: 'start' }, { error })}
        />
      </Screen>
    );
  }

  if (step.kind === 'saved') {
    const { log } = step;
    return (
      <Screen>
        <Card>
          <View style={[styles.row, { gap: spacing.sm }]}>
            <Ionicons name="checkmark-circle" size={28} color={colors.success} />
            <AppText variant="title">Meal saved</AppText>
          </View>
          <AppText>
            {amount(log.actual_cals)} kcal · protein {amount(log.actual_protein)} g · fat {amount(log.actual_fat)} g ·
            carbs {amount(log.actual_carbs)} g
          </AppText>
          <AppText color="textMuted">It counts towards today&apos;s totals.</AppText>
        </Card>
        <Button title="Scan another meal" onPress={() => setStep({ kind: 'start' })} />
      </Screen>
    );
  }

  if (step.kind === 'uploading') {
    const analysing = step.progress >= 1;
    return (
      <Screen>
        <Card>
          <Image
            source={{ uri: step.photo.uri }}
            style={[styles.photo, { borderRadius: spacing.sm }]}
            contentFit="cover"
            accessibilityLabel="Your meal photo"
          />
          <AppText variant="bodyStrong" accessibilityLiveRegion="polite">
            {analysing ? 'Analysing your meal…' : `Uploading ${Math.round(step.progress * 100)} %`}
          </AppText>
          <ProgressBar fraction={step.progress} />
          {analysing ? <ActivityIndicator accessibilityLabel="Analysing" /> : null}
          {step.slow ? (
            <AppText color="textMuted" accessibilityLiveRegion="polite">
              This is taking longer than usual. You can wait or cancel and try again.
            </AppText>
          ) : null}
        </Card>
        <Button title="Cancel" variant="ghost" onPress={() => cancelUpload.current?.()} />
      </Screen>
    );
  }

  return (
    <Screen>
      <Card>
        <AppText variant="title">Scan your meal</AppText>
        <AppText color="textMuted">
          Take a photo of your plate. AI recognises the products and estimates their grams; you check them before
          saving.
        </AppText>
      </Card>

      {step.kind === 'failed' ? (
        <Card style={{ borderColor: colors.danger, borderLeftWidth: 4 }} accessibilityRole="alert">
          <AppText variant="bodyStrong">The photo could not be analysed</AppText>
          <AppText>{step.message}</AppText>
          <Button title="Try again" onPress={() => send(step.photo)} />
        </Card>
      ) : null}
      <FormMessage message={notice} tone="info" />
      <FormMessage message={message} />

      <OptionGroup label="Meal" options={MEAL_TYPE_OPTIONS} value={mealType} onChange={setMealType} />
      <Button title="Take a photo" onPress={() => pick('camera')} />
      <Button title="Choose from gallery" variant="secondary" onPress={() => pick('gallery')} />
      <AppText variant="caption" color="textMuted">
        Only the photo is sent for analysis, never your name or other data. JPEG, PNG or WebP up to 8 MB.
      </AppText>
    </Screen>
  );
}

const styles = StyleSheet.create({
  photo: { width: '100%', height: 200 },
  track: { height: 8, width: '100%', overflow: 'hidden' },
  bar: { height: 8 },
  row: { flexDirection: 'row', alignItems: 'center' },
});
