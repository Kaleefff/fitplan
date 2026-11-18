import AsyncStorage from '@react-native-async-storage/async-storage';

import { api, unwrap } from '@/api/client';
import { ApiError, isErrorBody, networkError, userMessage } from '@/api/errors';
import type { components } from '@/api/schema';
import { authManager } from '@/auth/session';
import { config } from '@/config';

type Schemas = components['schemas'];
export type Recognition = Schemas['Recognition'];
export type RecognisedItem = Schemas['RecognisedItem'];
export type MealType = Schemas['MealType'];
export type NutritionLog = Schemas['NutritionLog'];
export type ConfirmInput = Schemas['ConfirmRecognitionRequest'];

/** RecognitionUpload: JPEG, PNG or WebP, at most 8 MB */
export const MAX_PHOTO_BYTES = 8 * 1024 * 1024;
export const PHOTO_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
/** NFR-PERF: photo analysis within 10 s; after that the screen says the request is slow */
export const SLOW_AFTER_MS = 10_000;
/** The upload gives up after this long without an answer */
export const UPLOAD_TIMEOUT_MS = 45_000;

export const MEAL_TYPE_OPTIONS: { value: MealType; label: string }[] = [
  { value: 'breakfast', label: 'Breakfast' },
  { value: 'lunch', label: 'Lunch' },
  { value: 'dinner', label: 'Dinner' },
  { value: 'snack', label: 'Snack' },
];

/** A first guess from the time of day; the user can change it before the upload */
export function defaultMealType(now: Date = new Date()): MealType {
  const minutes = now.getHours() * 60 + now.getMinutes();
  if (minutes < 10 * 60 + 30) return 'breakfast';
  if (minutes < 15 * 60) return 'lunch';
  if (minutes < 17 * 60 + 30) return 'snack';
  return 'dinner';
}

/** A photo picked with the camera or the gallery */
export type Photo = { uri: string; mimeType: string; fileName: string; fileSize: number | null };

/** Why the photo cannot be sent, checked before the upload; null when it can */
export function photoProblem(photo: Photo): string | null {
  if (!PHOTO_TYPES.includes(photo.mimeType)) {
    return 'Use a JPEG, PNG or WebP photo.';
  }
  if (photo.fileSize !== null && photo.fileSize > MAX_PHOTO_BYTES) {
    return 'This photo is larger than 8 MB. Take it again or choose a smaller one.';
  }
  return null;
}

export type Upload = { promise: Promise<Recognition>; cancel: () => void };
/** The upload was cancelled by the user */
export class UploadCancelled extends Error {}

type UploadDeps = {
  getToken: () => Promise<string | null>;
  refresh: () => Promise<string | null>;
  createRequest: () => XMLHttpRequest;
};

const defaultDeps: UploadDeps = {
  getToken: () => authManager.getAccessToken(),
  refresh: () => authManager.refresh(),
  createRequest: () => new XMLHttpRequest(),
};

/**
 * POST /meals/recognitions as multipart/form-data (FR-N1). XMLHttpRequest reports upload progress,
 * which fetch does not; the token is added as by the API client, with one refresh on 401.
 */
export function uploadPhoto(
  photo: Photo,
  mealType: MealType,
  onProgress: (fraction: number) => void,
  deps: UploadDeps = defaultDeps,
): Upload {
  let current: XMLHttpRequest | null = null;
  let cancelled = false;

  const attempt = (token: string | null) =>
    new Promise<{ status: number; body: unknown }>((resolve, reject) => {
      const request = deps.createRequest();
      current = request;
      request.open('POST', `${config.apiUrl}/meals/recognitions`);
      request.timeout = UPLOAD_TIMEOUT_MS;
      request.setRequestHeader('Accept', 'application/json');
      if (token) {
        request.setRequestHeader('Authorization', `Bearer ${token}`);
      }
      request.upload.onprogress = (event) => {
        if (event.lengthComputable && event.total > 0) {
          onProgress(Math.min(event.loaded / event.total, 1));
        }
      };
      request.onload = () => {
        let body: unknown = null;
        try {
          body = request.responseText ? JSON.parse(request.responseText) : null;
        } catch {
          body = null;
        }
        resolve({ status: request.status, body });
      };
      request.onerror = () => reject(networkError(new Error('upload failed')));
      request.ontimeout = () =>
        reject(new ApiError(0, 'timeout', 'The analysis took too long. Check your connection and try again.'));
      request.onabort = () => reject(new UploadCancelled('cancelled'));

      const form = new FormData();
      // React Native sends a file given as { uri, name, type }
      form.append('photo', { uri: photo.uri, name: photo.fileName, type: photo.mimeType } as unknown as Blob);
      form.append('meal_type', mealType);
      request.send(form);
    });

  const run = async (): Promise<Recognition> => {
    let answer = await attempt(await deps.getToken());
    if (answer.status === 401 && !cancelled) {
      const token = await deps.refresh();
      if (token) {
        onProgress(0);
        answer = await attempt(token);
      }
    }
    if (answer.status === 201) {
      return answer.body as Recognition;
    }
    if (isErrorBody(answer.body)) {
      throw new ApiError(answer.status, answer.body.code, answer.body.message, answer.body.details ?? []);
    }
    throw new ApiError(answer.status, 'unexpected_response', `The server answered ${answer.status}.`);
  };

  return {
    promise: run(),
    cancel: () => {
      cancelled = true;
      current?.abort();
    },
  };
}

const path = (recognitionId: string) => ({ params: { path: { recognition_id: recognitionId } } });

export function getRecognition(recognitionId: string): Promise<Recognition> {
  return unwrap(api.GET('/meals/recognitions/{recognition_id}', path(recognitionId)));
}

/** Deletes the pending document and its photo */
export async function discardRecognition(recognitionId: string): Promise<void> {
  await unwrap(api.DELETE('/meals/recognitions/{recognition_id}', path(recognitionId)));
}

/** Adds a product the model missed (FR-N4) */
export function addItem(recognitionId: string, foodItemId: number, grams: number): Promise<Recognition> {
  return unwrap(
    api.POST('/meals/recognitions/{recognition_id}/items', {
      ...path(recognitionId),
      body: { food_item_id: foodItemId, grams },
    }),
  );
}

/** Corrects the food or the grams of one item; the answer has the new totals (FR-N4) */
export function updateItem(
  recognitionId: string,
  index: number,
  change: Schemas['RecognitionItemPatch'],
): Promise<Recognition> {
  return unwrap(
    api.PATCH('/meals/recognitions/{recognition_id}/items/{item_index}', {
      params: { path: { recognition_id: recognitionId, item_index: index } },
      body: change,
    }),
  );
}

export function deleteItem(recognitionId: string, index: number): Promise<Recognition> {
  return unwrap(
    api.DELETE('/meals/recognitions/{recognition_id}/items/{item_index}', {
      params: { path: { recognition_id: recognitionId, item_index: index } },
    }),
  );
}

/** Writes the nutrition log; every item needs a food and grams above 0 */
export function confirmRecognition(recognitionId: string, input: ConfirmInput): Promise<NutritionLog> {
  return unwrap(api.POST('/meals/recognitions/{recognition_id}/confirm', { ...path(recognitionId), body: input }));
}

const PENDING_KEY = 'fitplan.pendingRecognitionId';

/**
 * Remembers the scan under review, so it survives an app restart until it is saved, discarded or
 * expires (6 h, mongo_buffer.md). Storage errors only lose this convenience.
 */
export const pendingScan = {
  async get(): Promise<string | null> {
    return AsyncStorage.getItem(PENDING_KEY).catch(() => null);
  },
  async set(recognitionId: string): Promise<void> {
    await AsyncStorage.setItem(PENDING_KEY, recognitionId).catch(() => undefined);
  },
  async clear(): Promise<void> {
    await AsyncStorage.removeItem(PENDING_KEY).catch(() => undefined);
  },
};

/** The remembered scan, or null when there is none or it expired */
export async function resumePendingScan(): Promise<Recognition | null> {
  const id = await pendingScan.get();
  if (!id) {
    return null;
  }
  try {
    return await getRecognition(id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      await pendingScan.clear();
      return null;
    }
    throw error;
  }
}

/** What still blocks confirming, checked before the request (the server checks it again) */
export function confirmProblem(recognition: Recognition): string | null {
  if (recognition.recognised_items.length === 0) {
    return 'Add at least one product before saving.';
  }
  if (recognition.recognised_items.some((item) => item.food_item_id === null)) {
    return 'Pick a food for every product marked "Pick a food".';
  }
  if (recognition.recognised_items.some((item) => Math.round(item.grams * 10) === 0)) {
    return 'Enter the grams of every product.';
  }
  return null;
}

/** Text for an error of the scanner flow; a pending scan expires after 6 h (404) */
export function scanErrorMessage(error: ApiError): string {
  switch (error.code) {
    case 'payload_too_large':
      return 'This photo is larger than 8 MB. Take it again or choose a smaller one.';
    case 'ai_unavailable':
      return 'The meal analysis is not available right now. Try again in a moment.';
    case 'timeout':
      return error.message;
    case 'not_found':
      return 'This scan has expired or was already saved. Take the photo again.';
    default:
      return userMessage(error);
  }
}

/** "0.92" -> "92 %" */
export const percent = (fraction: number) => `${Math.round(fraction * 100)} %`;

/** Grams and nutrition as the API gives them, one decimal at most */
export const amount = (value: number) => String(Math.round(value * 10) / 10);
