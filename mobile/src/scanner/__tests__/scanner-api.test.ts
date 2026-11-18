import AsyncStorage from '@react-native-async-storage/async-storage';

import { ApiError } from '@/api/errors';
import { allergyItems, checkGrams, itemFlags } from '@/scanner/review-form';
import {
  confirmProblem,
  defaultMealType,
  pendingScan,
  photoProblem,
  resumePendingScan,
  scanErrorMessage,
  UploadCancelled,
  uploadPhoto,
  type Recognition,
  type RecognisedItem,
} from '@/scanner/scanner-api';

const mockGet = jest.fn();
jest.mock('@/api/client', () => ({
  api: { GET: (...args: unknown[]) => mockGet(...args) },
  unwrap: (call: Promise<unknown>) => call,
}));
jest.mock('@/auth/session', () => ({ authManager: {} }));
jest.mock('@/config', () => ({ config: { apiUrl: 'http://api.test/api/v1' } }));

const item = (extra: Partial<RecognisedItem> = {}): RecognisedItem => ({
  name: 'rice',
  food_item_id: 2,
  grams: 180,
  confidence: 0.7,
  nutrition: { kcal: 234, protein: 4.9, fat: 0.5, carbs: 50.4 },
  corrected: false,
  low_confidence: false,
  allergy_warning: false,
  ...extra,
});

const recognition = (items: RecognisedItem[]): Recognition => ({
  id: 'a'.repeat(24),
  status: 'pending',
  meal_type: 'lunch',
  overall_confidence: 0.7,
  recognised_items: items,
  created_at: '2026-11-17T12:00:00Z',
  expires_at: '2026-11-17T18:00:00Z',
});

const photo = { uri: 'file:///meal.jpg', mimeType: 'image/jpeg', fileName: 'meal.jpg', fileSize: 1_000_000 };

/** A stand-in for XMLHttpRequest that answers when the test says so */
class FakeRequest {
  static made: FakeRequest[] = [];
  headers: Record<string, string> = {};
  method = '';
  url = '';
  timeout = 0;
  status = 0;
  responseText = '';
  sent: unknown = null;
  upload: { onprogress: ((event: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = {
    onprogress: null,
  };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  ontimeout: (() => void) | null = null;
  onabort: (() => void) | null = null;
  constructor() {
    FakeRequest.made.push(this);
  }
  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }
  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }
  send(body: unknown) {
    this.sent = body;
  }
  abort() {
    this.onabort?.();
  }
  answer(status: number, body: unknown) {
    this.status = status;
    this.responseText = JSON.stringify(body);
    this.onload?.();
  }
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

function deps(refreshTo: string | null = 'new-token') {
  return {
    getToken: jest.fn(() => Promise.resolve('token')),
    refresh: jest.fn(() => Promise.resolve(refreshTo)),
    createRequest: () => new FakeRequest() as unknown as XMLHttpRequest,
  };
}

describe('scanner rules', () => {
  it('guesses the meal from the time of day', () => {
    expect(defaultMealType(new Date(2026, 10, 17, 8, 0))).toBe('breakfast');
    expect(defaultMealType(new Date(2026, 10, 17, 13, 0))).toBe('lunch');
    expect(defaultMealType(new Date(2026, 10, 17, 16, 0))).toBe('snack');
    expect(defaultMealType(new Date(2026, 10, 17, 19, 30))).toBe('dinner');
  });

  it('checks type and size before the upload (8 MB, JPEG / PNG / WebP)', () => {
    expect(photoProblem(photo)).toBeNull();
    expect(photoProblem({ ...photo, mimeType: 'image/heic' })).toBe('Use a JPEG, PNG or WebP photo.');
    expect(photoProblem({ ...photo, fileSize: 9 * 1024 * 1024 })).toMatch(/larger than 8 MB/);
    // Size unknown: the server checks it (413)
    expect(photoProblem({ ...photo, fileSize: null })).toBeNull();
  });

  it('blocks confirming without a food or grams for every product', () => {
    expect(confirmProblem(recognition([item()]))).toBeNull();
    expect(confirmProblem(recognition([]))).toBe('Add at least one product before saving.');
    expect(confirmProblem(recognition([item({ food_item_id: null, grams: 0 })]))).toMatch(/Pick a food/);
    expect(confirmProblem(recognition([item({ grams: 0.04 })]))).toBe('Enter the grams of every product.');
  });

  it('explains the errors of the scanner flow', () => {
    expect(scanErrorMessage(new ApiError(413, 'payload_too_large', 'too big'))).toMatch(/larger than 8 MB/);
    expect(scanErrorMessage(new ApiError(503, 'ai_unavailable', 'down'))).toBe(
      'The meal analysis is not available right now. Try again in a moment.',
    );
    expect(scanErrorMessage(new ApiError(404, 'not_found', 'gone'))).toBe(
      'This scan has expired or was already saved. Take the photo again.',
    );
  });

  it('checks typed grams like the contract (> 0, at most 99999.9, 1 decimal)', () => {
    expect(checkGrams('150')).toBeNull();
    expect(checkGrams('12,5')).toBeNull();
    expect(checkGrams('0')).toBe('Enter from 0.1 to 99999.9 g.');
    expect(checkGrams('100000')).toBe('Enter from 0.1 to 99999.9 g.');
    expect(checkGrams('1.25')).toBe('Enter the grams, at most 1 decimal.');
    expect(checkGrams('')).toBe('Enter the grams, at most 1 decimal.');
  });

  it('flags products with an icon and a label, never colour alone', () => {
    expect(itemFlags(item({ food_item_id: null, allergy_warning: true, low_confidence: true }))).toEqual([
      'pick',
      'allergen',
      'unsure',
    ]);
    expect(allergyItems(recognition([item({ name: 'cheese', allergy_warning: true }), item()]))).toEqual(['Cheese']);
  });
});

describe('uploadPhoto (FR-N1)', () => {
  beforeEach(() => {
    FakeRequest.made = [];
  });

  it('sends the photo and the meal type with the token and reports progress', async () => {
    const progress: number[] = [];
    const upload = uploadPhoto(photo, 'lunch', (f) => progress.push(f), deps());
    await flush();
    const request = FakeRequest.made[0];

    expect(request.method).toBe('POST');
    expect(request.url).toBe('http://api.test/api/v1/meals/recognitions');
    expect(request.headers.Authorization).toBe('Bearer token');
    expect(request.sent).toBeInstanceOf(FormData);
    request.upload.onprogress!({ lengthComputable: true, loaded: 50, total: 100 });
    request.answer(201, recognition([item()]));

    await expect(upload.promise).resolves.toMatchObject({ meal_type: 'lunch' });
    expect(progress).toEqual([0.5]);
  });

  it('refreshes the token once after 401 and sends again', async () => {
    const d = deps();
    const upload = uploadPhoto(photo, 'lunch', () => undefined, d);
    await flush();
    FakeRequest.made[0].answer(401, { code: 'unauthorized', message: 'expired', details: [] });
    await flush();
    await flush();

    expect(d.refresh).toHaveBeenCalledTimes(1);
    expect(FakeRequest.made[1].headers.Authorization).toBe('Bearer new-token');
    FakeRequest.made[1].answer(201, recognition([]));
    await expect(upload.promise).resolves.toBeDefined();
  });

  it('turns an error answer into ApiError', async () => {
    const upload = uploadPhoto(photo, 'lunch', () => undefined, deps());
    await flush();
    FakeRequest.made[0].answer(503, { code: 'ai_unavailable', message: 'down', details: [] });

    await expect(upload.promise).rejects.toMatchObject({ status: 503, code: 'ai_unavailable' });
  });

  it('can be cancelled', async () => {
    const upload = uploadPhoto(photo, 'lunch', () => undefined, deps());
    await flush();
    upload.cancel();

    await expect(upload.promise).rejects.toBeInstanceOf(UploadCancelled);
  });
});

describe('pending scan', () => {
  beforeEach(async () => {
    jest.clearAllMocks();
    await AsyncStorage.clear();
  });

  it('resumes the remembered scan', async () => {
    await pendingScan.set('b'.repeat(24));
    mockGet.mockResolvedValue(recognition([item()]));

    expect(await resumePendingScan()).toMatchObject({ meal_type: 'lunch' });
    expect(mockGet).toHaveBeenCalledWith('/meals/recognitions/{recognition_id}', {
      params: { path: { recognition_id: 'b'.repeat(24) } },
    });
  });

  it('forgets an expired scan', async () => {
    await pendingScan.set('c'.repeat(24));
    mockGet.mockRejectedValue(new ApiError(404, 'not_found', 'expired'));

    expect(await resumePendingScan()).toBeNull();
    expect(await pendingScan.get()).toBeNull();
  });

  it('asks nothing when no scan is remembered', async () => {
    expect(await resumePendingScan()).toBeNull();
    expect(mockGet).not.toHaveBeenCalled();
  });
});
