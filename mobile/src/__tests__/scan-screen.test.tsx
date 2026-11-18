import { act, fireEvent, screen } from '@testing-library/react-native';

import { ApiError } from '@/api/errors';
import ScanScreen from '@/app/(tabs)/scan';
import type { Recognition, RecognisedItem } from '@/scanner/scanner-api';
import { renderWithTheme } from '@/test-utils';

const mockLaunchLibrary = jest.fn();
const mockLaunchCamera = jest.fn();
const mockCameraPermission = jest.fn();
jest.mock('expo-image-picker', () => ({
  launchImageLibraryAsync: (...args: unknown[]) => mockLaunchLibrary(...args),
  launchCameraAsync: (...args: unknown[]) => mockLaunchCamera(...args),
  requestCameraPermissionsAsync: () => mockCameraPermission(),
}));

const mockUpload = jest.fn();
const mockResume = jest.fn();
const mockUpdateItem = jest.fn();
const mockAddItem = jest.fn();
const mockDeleteItem = jest.fn();
const mockConfirm = jest.fn();
const mockDiscard = jest.fn();
jest.mock('@/scanner/scanner-api', () => ({
  ...jest.requireActual('@/scanner/scanner-api'),
  uploadPhoto: (...args: unknown[]) => mockUpload(...args),
  resumePendingScan: () => mockResume(),
  updateItem: (...args: unknown[]) => mockUpdateItem(...args),
  addItem: (...args: unknown[]) => mockAddItem(...args),
  deleteItem: (...args: unknown[]) => mockDeleteItem(...args),
  confirmRecognition: (...args: unknown[]) => mockConfirm(...args),
  discardRecognition: (...args: unknown[]) => mockDiscard(...args),
  pendingScan: { get: jest.fn(), set: jest.fn(() => Promise.resolve()), clear: jest.fn(() => Promise.resolve()) },
}));

const mockSearchFoods = jest.fn();
jest.mock('@/diet/diet-api', () => ({
  ...jest.requireActual('@/diet/diet-api'),
  searchFoods: (...args: unknown[]) => mockSearchFoods(...args),
}));

const ID = 'a'.repeat(24);
const item = (extra: Partial<RecognisedItem>): RecognisedItem => ({
  name: 'rice',
  food_item_id: 2,
  grams: 180,
  confidence: 0.71,
  nutrition: { kcal: 234, protein: 4.9, fat: 0.5, carbs: 50.4 },
  corrected: false,
  low_confidence: false,
  allergy_warning: false,
  ...extra,
});

function scan(items: RecognisedItem[], kcal = 606.6): Recognition {
  return {
    id: ID,
    status: 'pending',
    meal_type: 'lunch',
    overall_confidence: 0.92,
    recognised_items: items,
    totals: { kcal, protein: 60, fat: 14, carbs: 58 },
    created_at: '2026-11-17T12:00:00Z',
    expires_at: '2026-11-17T18:00:00Z',
  };
}

const firstScan = scan([
  item({ name: 'grilled chicken', food_item_id: 1, grams: 160, confidence: 0.92 }),
  item({}),
  item({ name: 'cheese', food_item_id: 4, grams: 20, allergy_warning: true }),
  item({
    name: 'sauce',
    food_item_id: null,
    grams: 0,
    confidence: 0.4,
    nutrition: { kcal: 0, protein: 0, fat: 0, carbs: 0 },
  }),
  item({ name: 'broccoli', food_item_id: 3, grams: 80, confidence: 0.22, low_confidence: true }),
]);

const asset = { uri: 'file:///meal.jpg', mimeType: 'image/jpeg', fileName: 'meal.jpg', fileSize: 2_000_000 };
const press = (name: string | RegExp) => fireEvent.press(screen.getByRole('button', { name }));
const pressWhenShown = async (name: string | RegExp) => fireEvent.press(await screen.findByRole('button', { name }));

async function scanFromGallery(result: Promise<Recognition>) {
  mockLaunchLibrary.mockResolvedValue({ canceled: false, assets: [asset] });
  mockUpload.mockReturnValue({ promise: result, cancel: jest.fn() });
  await renderWithTheme(<ScanScreen />);
  await pressWhenShown('Choose from gallery');
}

describe('ScanScreen (M-15)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockResume.mockResolvedValue(null);
  });

  it('uploads the photo and shows the allergy warning and the products to check before saving', async () => {
    await scanFromGallery(Promise.resolve(firstScan));

    expect(mockUpload).toHaveBeenCalledWith(
      { uri: 'file:///meal.jpg', mimeType: 'image/jpeg', fileName: 'meal.jpg', fileSize: 2_000_000 },
      expect.any(String),
      expect.any(Function),
    );
    expect(await screen.findByText('Allergy warning')).toBeOnTheScreen();
    expect(screen.getByText(/Cheese contains one of your allergens/)).toBeOnTheScreen();
    expect(screen.getByText('606.6 kcal')).toBeOnTheScreen();
    expect(screen.getByRole('button', { name: /^Sauce, 0 grams, 0 kcal, Pick a food/ })).toBeOnTheScreen();
    expect(screen.getByRole('button', { name: /^Broccoli, .*Not sure, check it/ })).toBeOnTheScreen();

    await press('Save meal');
    expect(screen.getByText('Pick a food for every product marked "Pick a food".')).toBeOnTheScreen();
    expect(mockConfirm).not.toHaveBeenCalled();
  });

  it('corrects grams and the totals follow the server (M-15 Done)', async () => {
    await scanFromGallery(Promise.resolve(firstScan));
    mockUpdateItem.mockResolvedValue(
      scan(
        firstScan.recognised_items.map((it, i) => (i === 1 ? { ...it, grams: 100, corrected: true } : it)),
        502.6,
      ),
    );

    await pressWhenShown(/^Rice, 180 grams/);
    await fireEvent.changeText(screen.getByLabelText('Grams'), '100');
    await press('Save grams');

    expect(mockUpdateItem).toHaveBeenCalledWith(ID, 1, { grams: 100 });
    expect(await screen.findByText('502.6 kcal')).toBeOnTheScreen();
  });

  it('picks a food for an unmatched product', async () => {
    await scanFromGallery(Promise.resolve(firstScan));
    mockSearchFoods.mockResolvedValue([{ id: 5, name: 'Olive oil', cals_per_100g: 884, default_portion_g: 10 }]);
    mockUpdateItem.mockResolvedValue(scan([item({ name: 'Olive oil', food_item_id: 5, grams: 10 })], 88.4));

    await pressWhenShown(/^Sauce/);
    await press('Pick a food');
    await fireEvent.changeText(screen.getByLabelText('Find a food'), 'oil');
    await fireEvent.press(await screen.findByRole('button', { name: 'Olive oil, 884 kcal per 100 g' }));

    // The product had no grams, so the food's usual portion is sent with it
    expect(mockUpdateItem).toHaveBeenCalledWith(ID, 3, { food_item_id: 5, grams: 10 });
    expect(await screen.findByText('88.4 kcal')).toBeOnTheScreen();
  });

  it('removes a product, then saves the meal with the hunger levels', async () => {
    const clean = scan([item({})], 234);
    await scanFromGallery(Promise.resolve(firstScan));
    mockDeleteItem.mockResolvedValue(clean);
    mockConfirm.mockResolvedValue({ actual_cals: 234, actual_protein: 4.9, actual_fat: 0.5, actual_carbs: 50.4 });

    await pressWhenShown(/^Cheese/);
    await press('Remove');
    expect(mockDeleteItem).toHaveBeenCalledWith(ID, 2);
    await screen.findByText('234 kcal');

    await fireEvent.press(screen.getAllByRole('radio', { name: '6' })[0]);
    await press('Save meal');

    expect(mockConfirm).toHaveBeenCalledWith(ID, { hunger_level_before: 6, hunger_level_after: null });
    expect(await screen.findByText('Meal saved')).toBeOnTheScreen();
  });

  it('discards the scan', async () => {
    await scanFromGallery(Promise.resolve(firstScan));
    mockDiscard.mockResolvedValue(undefined);

    await pressWhenShown('Discard');

    expect(mockDiscard).toHaveBeenCalledWith(ID);
    expect(await screen.findByText('The scan was discarded.')).toBeOnTheScreen();
  });

  it('starts again when the scan has expired', async () => {
    await scanFromGallery(Promise.resolve(firstScan));
    mockDiscard.mockRejectedValue(new ApiError(404, 'not_found', 'gone'));

    await pressWhenShown('Discard');

    expect(
      await screen.findByText('This scan has expired or was already saved. Take the photo again.'),
    ).toBeOnTheScreen();
    expect(screen.getByRole('button', { name: 'Take a photo' })).toBeOnTheScreen();
  });

  it('offers to send the same photo again when the AI is not available', async () => {
    await scanFromGallery(Promise.reject(new ApiError(503, 'ai_unavailable', 'down')));

    expect(
      await screen.findByText('The meal analysis is not available right now. Try again in a moment.'),
    ).toBeOnTheScreen();
    mockUpload.mockReturnValue({ promise: Promise.resolve(firstScan), cancel: jest.fn() });
    await press('Try again');

    expect(mockUpload).toHaveBeenCalledTimes(2);
    expect(await screen.findByText('Allergy warning')).toBeOnTheScreen();
  });

  it('shows the upload progress and says when the analysis is slow', async () => {
    let progress: (fraction: number) => void = () => undefined;
    mockLaunchLibrary.mockResolvedValue({ canceled: false, assets: [asset] });
    mockUpload.mockImplementation((_photo, _meal, onProgress) => {
      progress = onProgress;
      return { promise: new Promise(() => undefined), cancel: jest.fn() };
    });
    await renderWithTheme(<ScanScreen />);
    const gallery = await screen.findByRole('button', { name: 'Choose from gallery' });
    // The 10 s wait for the slow message starts with the upload
    jest.useFakeTimers();
    try {
      await act(async () => {
        fireEvent.press(gallery);
      });

      await act(() => progress(0.4));
      expect(screen.getByText('Uploading 40 %')).toBeOnTheScreen();
      await act(() => progress(1));
      expect(screen.getByText('Analysing your meal…')).toBeOnTheScreen();
      await act(() => jest.advanceTimersByTime(10_000));
      expect(screen.getByText(/taking longer than usual/)).toBeOnTheScreen();
    } finally {
      jest.useRealTimers();
    }
  });

  it('asks for the camera and explains a refusal', async () => {
    mockCameraPermission.mockResolvedValue({ granted: false });
    await renderWithTheme(<ScanScreen />);

    await pressWhenShown('Take a photo');

    expect(
      screen.getByText('Allow camera access in the system settings, or choose a photo from the gallery.'),
    ).toBeOnTheScreen();
    expect(mockLaunchCamera).not.toHaveBeenCalled();
  });

  it('rejects a photo above 8 MB before sending it', async () => {
    mockLaunchLibrary.mockResolvedValue({ canceled: false, assets: [{ ...asset, fileSize: 9 * 1024 * 1024 }] });
    await renderWithTheme(<ScanScreen />);

    await pressWhenShown('Choose from gallery');

    expect(
      screen.getByText('This photo is larger than 8 MB. Take it again or choose a smaller one.'),
    ).toBeOnTheScreen();
    expect(mockUpload).not.toHaveBeenCalled();
  });

  it('resumes a scan left under review', async () => {
    mockResume.mockResolvedValue(firstScan);
    await renderWithTheme(<ScanScreen />);

    expect(await screen.findByText('Allergy warning')).toBeOnTheScreen();
    expect(mockUpload).not.toHaveBeenCalled();
  });
});
