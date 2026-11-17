/**
 * Mock of the FitPlan Pro API for app development (M-01).
 * Implements the operations the app uses so far, keeps data in memory and types every
 * answer with the schemas generated from docs/api/openapi.yaml, so `npm run typecheck`
 * fails when the mock drifts from the contract.
 *
 * Run: `npm run mock` (port 4010, change with MOCK_PORT); data is lost on restart.
 * Business rules are simplified; the real backend is the reference.
 */
import { randomBytes, randomUUID } from 'node:crypto';
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';

import type { components } from '../src/api/schema';

type Schemas = components['schemas'];

const PORT = Number(process.env.MOCK_PORT ?? 4010);
const PREFIX = '/api/v1';
const ACCESS_TOKEN_SECONDS = 900;

// ---------------------------------------------------------------- reference data

const muscleGroups: Schemas['MuscleGroup'][] = [
  'chest', 'back', 'shoulders', 'biceps', 'triceps',
  'quadriceps', 'hamstrings', 'glutes', 'calves', 'core',
].map((name, index) => ({ id: index + 1, group_name: name, description: `${name} muscles`, image_url: null }));

const injuryTypes: Schemas['InjuryType'][] = [
  ['Sprain', 14], ['Strain', 21], ['Tendinitis', 42], ['Dislocation', 56], ['Lower back pain', 28],
].map(([name, days], index) => ({
  id: index + 1,
  type_name: String(name),
  description: `${name} (mock data)`,
  avg_healing_time_days: Number(days),
}));

const allergens: Schemas['Allergen'][] = [
  'Gluten', 'Crustaceans', 'Eggs', 'Fish', 'Peanuts', 'Soybeans', 'Milk', 'Tree nuts',
  'Celery', 'Mustard', 'Sesame', 'Sulphites', 'Lupin', 'Molluscs', 'Lactose',
].map((name, index) => ({ id: index + 1, name, description: `${name} (mock data)` }));

// ---------------------------------------------------------------- in-memory state

type StoredUser = Schemas['User'] & { password: string };

const users: StoredUser[] = [];
const profiles = new Map<number, Schemas['Profile']>();
const injuries = new Map<number, Schemas['Injury'][]>();
const userAllergens = new Map<number, number[]>();
const accessTokens = new Map<string, { userId: number; expiresAt: number }>();
const refreshTokens = new Map<string, number>();
let nextInjuryId = 1;

// ---------------------------------------------------------------- helpers

type Detail = Schemas['ErrorDetail'];

class HttpError extends Error {
  status: number;
  code: Schemas['Error']['code'];
  details: Detail[];

  constructor(status: number, code: Schemas['Error']['code'], message: string, details: Detail[] = []) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function validationError(details: Detail[]): HttpError {
  return new HttpError(422, 'validation_error', 'Request validation failed', details);
}

function send(res: ServerResponse, status: number, body?: unknown) {
  res.writeHead(status, body === undefined ? {} : { 'Content-Type': 'application/json' });
  res.end(body === undefined ? undefined : JSON.stringify(body));
}

async function readJson(req: IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) {
    chunks.push(chunk as Buffer);
  }
  const text = Buffer.concat(chunks).toString('utf8');
  if (!text) {
    return {};
  }
  try {
    const value: unknown = JSON.parse(text);
    if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
      return value as Record<string, unknown>;
    }
  } catch {
    // reported below
  }
  throw validationError([{ field: 'body', code: 'json_invalid', message: 'Body must be a JSON object' }]);
}

function issueTokens(userId: number): Schemas['TokenPair'] {
  const access = randomBytes(24).toString('hex');
  const refresh = randomBytes(24).toString('hex');
  accessTokens.set(access, { userId, expiresAt: Date.now() + ACCESS_TOKEN_SECONDS * 1000 });
  refreshTokens.set(refresh, userId);
  return { access_token: access, refresh_token: refresh, token_type: 'bearer', expires_in: ACCESS_TOKEN_SECONDS };
}

function currentUser(req: IncomingMessage): StoredUser {
  const header = req.headers.authorization ?? '';
  const token = header.startsWith('Bearer ') ? header.slice('Bearer '.length) : '';
  const session = accessTokens.get(token);
  const user = session && session.expiresAt > Date.now() ? users.find((u) => u.id === session.userId) : undefined;
  if (!user) {
    throw new HttpError(401, 'unauthorized', 'Missing, expired or invalid token');
  }
  return user;
}

function publicUser({ password: _password, ...user }: StoredUser): Schemas['User'] {
  return user;
}

// Same rule as the backend: 8-72 bytes in UTF-8 with a letter and a digit
function passwordOk(password: unknown): boolean {
  if (typeof password !== 'string') {
    return false;
  }
  const bytes = Buffer.byteLength(password, 'utf8');
  return bytes >= 8 && bytes <= 72 && /\p{L}/u.test(password) && /\d/.test(password);
}

function text(body: Record<string, unknown>, field: string, details: Detail[], max = 100): string {
  const value = typeof body[field] === 'string' ? (body[field] as string).trim() : '';
  if (!value) {
    details.push({ field: `body.${field}`, code: 'missing', message: 'Field required' });
  } else if (value.length > max) {
    details.push({ field: `body.${field}`, code: 'string_too_long', message: `At most ${max} characters` });
  }
  return value;
}

function numberIn(
  body: Record<string, unknown>,
  field: string,
  min: number,
  max: number,
  details: Detail[],
  integer = false,
): number {
  const value = body[field];
  if (typeof value !== 'number' || Number.isNaN(value)) {
    details.push({ field: `body.${field}`, code: 'missing', message: 'Field required' });
    return 0;
  }
  if ((integer && !Number.isInteger(value)) || value < min || value > max) {
    details.push({
      field: `body.${field}`,
      code: 'out_of_range',
      message: `Must be ${integer ? 'a whole number ' : ''}between ${min} and ${max}`,
    });
  }
  return value;
}

function oneOf<T extends string | number>(
  body: Record<string, unknown>,
  field: string,
  allowed: readonly T[],
  details: Detail[],
): T {
  const value = body[field] as T;
  if (!allowed.includes(value)) {
    details.push({ field: `body.${field}`, code: 'enum', message: `Must be one of: ${allowed.join(', ')}` });
  }
  return value;
}

// algorithms.md sections 1 and 2
const GOAL_FACTORS: Record<Schemas['Goal'], { kcal: number; proteinPerKg: number; fatShare: number }> = {
  weight_loss: { kcal: 0.8, proteinPerKg: 2.0, fatShare: 0.3 },
  muscle_gain: { kcal: 1.1, proteinPerKg: 1.8, fatShare: 0.25 },
  strength: { kcal: 1.05, proteinPerKg: 1.8, fatShare: 0.25 },
  maintenance: { kcal: 1.0, proteinPerKg: 1.6, fatShare: 0.3 },
  general_fitness: { kcal: 1.0, proteinPerKg: 1.6, fatShare: 0.3 },
  endurance: { kcal: 1.05, proteinPerKg: 1.4, fatShare: 0.2 },
};

const round1 = (value: number) => Math.round(value * 10) / 10;

function bmrOf(profile: Schemas['ProfileInput']): number {
  const sexTerm = profile.sex === 'male' ? 5 : profile.sex === 'female' ? -161 : -78;
  return 10 * profile.current_weight + 6.25 * profile.height - 5 * profile.age + sexTerm;
}

function targetsOf(profile: Schemas['Profile']): Schemas['NutritionTargets'] {
  const factors = GOAL_FACTORS[profile.goal];
  const floor = profile.sex === 'male' ? 1500 : 1200;
  const targetKcal = Math.max(Math.round(profile.tdee * factors.kcal), floor);
  const protein = Math.min(factors.proteinPerKg * profile.current_weight, (0.35 * targetKcal) / 4);
  const fat = (factors.fatShare * targetKcal) / 9;
  return {
    goal: profile.goal,
    bmr: round1(bmrOf(profile)),
    tdee: profile.tdee,
    target_kcal: targetKcal,
    protein_g: round1(protein),
    fat_g: round1(fat),
    carbs_g: round1((targetKcal - 4 * protein - 9 * fat) / 4),
  };
}

// ---------------------------------------------------------------- operations

type Handler = (req: IncomingMessage, res: ServerResponse) => Promise<void> | void;

async function register(req: IncomingMessage, res: ServerResponse) {
  const body = await readJson(req);
  const details: Detail[] = [];
  const email = text(body, 'email', details).toLowerCase();
  if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    details.push({ field: 'body.email', code: 'value_error', message: 'Enter a valid email address' });
  }
  if (!passwordOk(body.password)) {
    details.push({
      field: 'body.password',
      code: 'value_error',
      message: 'Value error, Password must be 8-72 bytes with at least one letter and one digit',
    });
  }
  const name = text(body, 'name', details);
  const surname = text(body, 'surname', details);
  if (details.length > 0) {
    throw validationError(details);
  }
  if (users.some((u) => u.email === email)) {
    throw new HttpError(409, 'conflict', 'Email already registered');
  }
  const user: StoredUser = {
    id: users.length + 1,
    email,
    name,
    surname,
    timezone: 'Europe/Warsaw',
    registration_date: new Date().toISOString().slice(0, 10),
    password: body.password as string,
  };
  users.push(user);
  send(res, 201, issueTokens(user.id));
}

async function login(req: IncomingMessage, res: ServerResponse) {
  const body = await readJson(req);
  const email = typeof body.email === 'string' ? body.email.trim().toLowerCase() : '';
  const user = users.find((u) => u.email === email && u.password === body.password);
  if (!user) {
    throw new HttpError(401, 'invalid_credentials', 'Invalid email or password');
  }
  send(res, 200, issueTokens(user.id));
}

async function refresh(req: IncomingMessage, res: ServerResponse) {
  const body = await readJson(req);
  const token = typeof body.refresh_token === 'string' ? body.refresh_token : '';
  const userId = refreshTokens.get(token);
  if (userId === undefined) {
    throw new HttpError(401, 'unauthorized', 'Invalid refresh token');
  }
  refreshTokens.delete(token); // rotation: a used token never works again
  send(res, 200, issueTokens(userId));
}

async function logout(req: IncomingMessage, res: ServerResponse) {
  currentUser(req);
  const body = await readJson(req);
  if (typeof body.refresh_token === 'string') {
    refreshTokens.delete(body.refresh_token);
  }
  send(res, 204);
}

async function putProfile(req: IncomingMessage, res: ServerResponse) {
  const user = currentUser(req);
  const body = await readJson(req);
  const details: Detail[] = [];
  const input: Schemas['ProfileInput'] = {
    age: numberIn(body, 'age', 16, 100, details, true),
    sex: oneOf(body, 'sex', ['male', 'female', 'other'] as const, details),
    current_weight: numberIn(body, 'current_weight', 30, 300, details),
    height: numberIn(body, 'height', 120, 250, details, true),
    activity_level_pal: oneOf(body, 'activity_level_pal', [1.2, 1.375, 1.55, 1.725, 1.9] as const, details),
    goal: oneOf(body, 'goal', Object.keys(GOAL_FACTORS) as Schemas['Goal'][], details),
    target_value:
      body.target_value === null || body.target_value === undefined
        ? null
        : numberIn(body, 'target_value', 30, 300, details),
    experience_level: oneOf(body, 'experience_level', ['beginner', 'intermediate', 'advanced'] as const, details),
    equipment: oneOf(body, 'equipment', ['none', 'home', 'gym'] as const, details),
  };
  if (details.length > 0) {
    throw validationError(details);
  }
  const profile: Schemas['Profile'] = {
    ...input,
    tdee: Math.round(bmrOf(input) * input.activity_level_pal),
    profile_update: new Date().toISOString(),
  };
  profiles.set(user.id, profile);
  send(res, 200, profile);
}

function getProfile(req: IncomingMessage, res: ServerResponse) {
  const profile = profiles.get(currentUser(req).id);
  if (!profile) {
    throw new HttpError(404, 'not_found', 'Profile not found');
  }
  send(res, 200, profile);
}

async function createInjury(req: IncomingMessage, res: ServerResponse) {
  const user = currentUser(req);
  const body = await readJson(req);
  const details: Detail[] = [];
  const injuryTypeId = numberIn(body, 'injury_type_id', 1, injuryTypes.length, details, true);
  const muscleGroupId = numberIn(body, 'affected_muscle_group_id', 1, muscleGroups.length, details, true);
  const severity = oneOf(body, 'severity', ['mild', 'moderate', 'severe'] as const, details);
  const startDate = typeof body.start_date === 'string' ? body.start_date : '';
  if (!/^\d{4}-\d{2}-\d{2}$/.test(startDate)) {
    details.push({ field: 'body.start_date', code: 'date_parsing', message: 'Use the format YYYY-MM-DD' });
  } else if (startDate > new Date().toISOString().slice(0, 10)) {
    details.push({ field: 'body.start_date', code: 'future_date', message: 'Start date cannot be in the future' });
  }
  if (details.length > 0) {
    throw validationError(details);
  }
  const injury: Schemas['Injury'] = {
    id: nextInjuryId++,
    injury_type_id: injuryTypeId,
    affected_muscle_group_id: muscleGroupId,
    severity,
    start_date: startDate,
    is_active: body.is_active !== false,
  };
  injuries.set(user.id, [...(injuries.get(user.id) ?? []), injury]);
  send(res, 201, injury);
}

async function putAllergies(req: IncomingMessage, res: ServerResponse) {
  const user = currentUser(req);
  const body = await readJson(req);
  const ids = Array.isArray(body.allergen_ids) ? body.allergen_ids : null;
  if (!ids || ids.some((id) => !allergens.some((a) => a.id === id))) {
    throw validationError([{ field: 'body.allergen_ids', code: 'not_found', message: 'Unknown allergen id' }]);
  }
  const unique = [...new Set(ids as number[])];
  userAllergens.set(user.id, unique);
  send(res, 200, allergens.filter((a) => unique.includes(a.id)));
}

function nutritionTargets(req: IncomingMessage, res: ServerResponse) {
  const profile = profiles.get(currentUser(req).id);
  if (!profile) {
    throw new HttpError(404, 'not_found', 'Profile not found');
  }
  send(res, 200, targetsOf(profile));
}

// Reference lists also need a signed-in user
function sendReference(req: IncomingMessage, res: ServerResponse, list: unknown[]) {
  currentUser(req);
  send(res, 200, list);
}

// ---------------------------------------------------------------- foods and meal scanner (M-15)

type Food = Schemas['FoodItem'];

function food(
  id: number,
  name: string,
  [kcal, protein, fat, carbs]: [number, number, number, number],
  role: Food['diet_role'],
  portion: number,
  allergenIds: number[] = [],
): Food {
  return {
    id,
    name,
    cals_per_100g: kcal,
    protein_per_100g: protein,
    fat_per_100g: fat,
    carbs_per_100g: carbs,
    diet_role: role,
    suitable_meal_types: ['breakfast', 'lunch', 'dinner', 'snack'],
    is_vegetarian: role !== 'protein',
    is_vegan: role !== 'protein' && allergenIds.length === 0,
    default_portion_g: portion,
    min_portion_g: 10,
    max_portion_g: 500,
    portion_step_g: 10,
    category_ids: [],
    allergen_ids: allergenIds,
  };
}

// Allergen 7 is Milk in the list above
const foods: Food[] = [
  food(1, 'Chicken breast, grilled', [165, 31, 3.6, 0], 'protein', 150),
  food(2, 'White rice, cooked', [130, 2.7, 0.3, 28], 'carb', 150),
  food(3, 'Broccoli, steamed', [35, 2.4, 0.4, 7.2], 'vegetable', 100),
  food(4, 'Cheddar cheese', [403, 25, 33, 1.3], 'dairy', 30, [7]),
  food(5, 'Olive oil', [884, 0, 100, 0], 'fat', 10),
  food(6, 'Banana', [89, 1.1, 0.3, 23], 'fruit', 120),
  food(7, 'Oat flakes', [379, 13, 6.5, 68], 'carb', 50),
  food(8, 'Greek yogurt', [97, 9, 5, 3.9], 'dairy', 150, [7]),
];

function listFoods(req: IncomingMessage, res: ServerResponse) {
  currentUser(req);
  const query = new URL(req.url ?? '/', 'http://mock').searchParams;
  const q = (query.get('q') ?? '').trim().toLowerCase();
  const limit = Math.min(Number(query.get('limit') ?? 20) || 20, 100);
  const items = foods.filter((f) => f.name.toLowerCase().includes(q));
  send(res, 200, { total: items.length, limit, offset: 0, items: items.slice(0, limit) } satisfies Schemas['FoodPage']);
}

type StoredScan = { userId: number; doc: Schemas['Recognition']; edited: boolean };
const scans = new Map<string, StoredScan>();
const nutritionLogs: Schemas['NutritionLog'][] = [];
const MAX_PHOTO_BYTES = 8 * 1024 * 1024;
/** MOCK_SCAN_DELAY_MS=12000 shows the slow-request message; MOCK_SCAN_FAIL=1 answers 503 */
const SCAN_DELAY_MS = Number(process.env.MOCK_SCAN_DELAY_MS ?? 1500);
const SCAN_FAIL = process.env.MOCK_SCAN_FAIL === '1';

const round = (value: number, places: number) => Math.round(value * 10 ** places) / 10 ** places;

function scanItem(
  userId: number,
  name: string,
  foodId: number | null,
  grams: number,
  confidence: number,
): Schemas['RecognisedItem'] {
  const match = foods.find((f) => f.id === foodId);
  const factor = grams / 100;
  const allergens = userAllergens.get(userId) ?? [];
  return {
    name,
    food_item_id: match ? match.id : null,
    grams,
    confidence,
    nutrition: {
      kcal: match ? round(match.cals_per_100g * factor, 2) : 0,
      protein: match ? round(match.protein_per_100g * factor, 2) : 0,
      fat: match ? round(match.fat_per_100g * factor, 2) : 0,
      carbs: match ? round(match.carbs_per_100g * factor, 2) : 0,
    },
    corrected: false,
    low_confidence: confidence < 0.3,
    allergy_warning: match ? match.allergen_ids.some((id) => allergens.includes(id)) : false,
  };
}

function withTotals(doc: Schemas['Recognition']): Schemas['Recognition'] {
  const sum = (key: keyof Schemas['Macros']) =>
    round(
      doc.recognised_items.reduce((total, item) => total + item.nutrition[key], 0),
      2,
    );
  return {
    ...doc,
    overall_confidence: Math.max(0, ...doc.recognised_items.map((i) => i.confidence)),
    totals: { kcal: sum('kcal'), protein: sum('protein'), fat: sum('fat'), carbs: sum('carbs') },
  };
}

async function createRecognition(req: IncomingMessage, res: ServerResponse) {
  const user = currentUser(req);
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of req) {
    size += (chunk as Buffer).length;
    chunks.push(chunk as Buffer);
  }
  if (size > MAX_PHOTO_BYTES + 64 * 1024) {
    throw new HttpError(413, 'payload_too_large', 'The photo is larger than 8 MB');
  }
  const body = Buffer.concat(chunks).toString('latin1');
  const mealType = /name="meal_type"\r\n\r\n(\w+)/.exec(body)?.[1];
  const details: Detail[] = [];
  if (!/name="photo"/.test(body)) {
    details.push({ field: 'body.photo', code: 'missing', message: 'Field required' });
  }
  if (!mealType || !['breakfast', 'lunch', 'dinner', 'snack'].includes(mealType)) {
    details.push({ field: 'body.meal_type', code: 'enum', message: 'Unknown meal type' });
  }
  if (details.length > 0) {
    throw validationError(details);
  }
  await new Promise((resolve) => setTimeout(resolve, SCAN_DELAY_MS));
  if (SCAN_FAIL) {
    throw new HttpError(503, 'ai_unavailable', 'The AI service did not answer in time');
  }
  // Canned result: matched items, one unsure, one with a milk allergen, one not in the food database
  const id = randomBytes(12).toString('hex');
  const now = Date.now();
  const doc = withTotals({
    id,
    status: 'pending',
    meal_type: mealType as Schemas['MealType'],
    photo_url: null,
    overall_confidence: 0,
    recognised_items: [
      scanItem(user.id, 'grilled chicken', 1, 160, 0.92),
      scanItem(user.id, 'rice', 2, 180, 0.71),
      scanItem(user.id, 'broccoli', 3, 80, 0.22),
      scanItem(user.id, 'cheese', 4, 20, 0.55),
      scanItem(user.id, 'sauce', null, 0, 0.4),
    ],
    created_at: new Date(now).toISOString(),
    expires_at: new Date(now + 6 * 3600 * 1000).toISOString(),
  });
  scans.set(id, { userId: user.id, doc, edited: false });
  send(res, 201, doc);
}

function ownScan(req: IncomingMessage, id: string): StoredScan {
  const scan = scans.get(id);
  if (!scan || scan.userId !== currentUser(req).id) {
    throw new HttpError(404, 'not_found', 'Recognition not found or expired');
  }
  return scan;
}

function gramsFrom(body: Record<string, unknown>, details: Detail[], required: boolean): number | undefined {
  const grams = body.grams;
  if (grams === undefined && !required) return undefined;
  if (typeof grams !== 'number' || grams <= 0 || grams > 99999.9) {
    details.push({ field: 'body.grams', code: 'out_of_range', message: 'Grams must be above 0 and at most 99999.9' });
    return undefined;
  }
  return round(grams, 1);
}

function foodFrom(body: Record<string, unknown>, details: Detail[], required: boolean): Food | undefined {
  if (body.food_item_id === undefined && !required) return undefined;
  const match = foods.find((f) => f.id === body.food_item_id);
  if (!match) {
    details.push({ field: 'body.food_item_id', code: 'not_found', message: 'Unknown food' });
  }
  return match;
}

function confirmScan(scan: StoredScan, body: Record<string, unknown>): Schemas['NutritionLog'] {
  const items = scan.doc.recognised_items;
  const details: Detail[] = [];
  items.forEach((item, i) => {
    if (item.food_item_id === null) {
      details.push({ field: `body.recognised_items.${i}.food_item_id`, code: 'missing', message: 'Pick a food' });
    } else if (Math.round(item.grams * 10) === 0) {
      details.push({ field: `body.recognised_items.${i}.grams`, code: 'invalid_value', message: 'Grams round to 0.0' });
    }
  });
  if (items.length === 0) details.push({ field: 'body', code: 'missing', message: 'No items' });
  if (details.length > 0) throw validationError(details);
  const hunger = (field: string) => (typeof body[field] === 'number' ? (body[field] as number) : null);
  return {
    id: nutritionLogs.length + 1,
    client_uuid: randomUUID(),
    log_date: typeof body.log_date === 'string' ? body.log_date : new Date().toISOString().slice(0, 10),
    meal_type: scan.doc.meal_type,
    planned_meal_id: null,
    meal_photo_url: null,
    ai_confidence: scan.doc.overall_confidence,
    ai_was_edited: scan.edited,
    actual_cals: scan.doc.totals?.kcal ?? 0,
    actual_protein: scan.doc.totals?.protein ?? 0,
    actual_fat: scan.doc.totals?.fat ?? 0,
    actual_carbs: scan.doc.totals?.carbs ?? 0,
    hunger_level_before: hunger('hunger_level_before'),
    hunger_level_after: hunger('hunger_level_after'),
    logged_at: new Date().toISOString(),
    items: items.map((item) => ({ food_item_id: item.food_item_id!, name: item.name, grams: item.grams })),
  };
}

type ParamHandler = (req: IncomingMessage, res: ServerResponse, params: string[]) => Promise<void> | void;

const patternRoutes: [RegExp, Partial<Record<string, ParamHandler>>][] = [
  [
    /^\/meals\/recognitions\/([0-9a-f]{24})$/,
    {
      GET: (req, res, [id]) => send(res, 200, ownScan(req, id).doc),
      DELETE: (req, res, [id]) => {
        ownScan(req, id);
        scans.delete(id);
        send(res, 204);
      },
    },
  ],
  [
    /^\/meals\/recognitions\/([0-9a-f]{24})\/items$/,
    {
      POST: async (req, res, [id]) => {
        const scan = ownScan(req, id);
        const body = await readJson(req);
        const details: Detail[] = [];
        const match = foodFrom(body, details, true);
        const grams = gramsFrom(body, details, true);
        if (details.length > 0 || !match || grams === undefined) throw validationError(details);
        const item = { ...scanItem(scan.userId, match.name, match.id, grams, 1), corrected: true };
        scan.doc = withTotals({ ...scan.doc, recognised_items: [...scan.doc.recognised_items, item] });
        scan.edited = true;
        send(res, 200, scan.doc);
      },
    },
  ],
  [
    /^\/meals\/recognitions\/([0-9a-f]{24})\/items\/(\d+)$/,
    {
      PATCH: async (req, res, [id, index]) => {
        const scan = ownScan(req, id);
        const item = scan.doc.recognised_items[Number(index)];
        if (!item) throw new HttpError(404, 'not_found', 'No such item');
        const body = await readJson(req);
        const details: Detail[] = [];
        const match = foodFrom(body, details, false);
        const grams = gramsFrom(body, details, false);
        if (details.length > 0) throw validationError(details);
        if (!match && grams === undefined) {
          throw validationError([{ field: 'body', code: 'missing', message: 'Send food_item_id or grams' }]);
        }
        const foodId = match ? match.id : item.food_item_id;
        const name = match ? match.name : item.name;
        const next = { ...scanItem(scan.userId, name, foodId, grams ?? item.grams, item.confidence), corrected: true };
        const items = scan.doc.recognised_items.map((it, i) => (i === Number(index) ? next : it));
        scan.doc = withTotals({ ...scan.doc, recognised_items: items });
        scan.edited = true;
        send(res, 200, scan.doc);
      },
      DELETE: (req, res, [id, index]) => {
        const scan = ownScan(req, id);
        if (!scan.doc.recognised_items[Number(index)]) throw new HttpError(404, 'not_found', 'No such item');
        const items = scan.doc.recognised_items.filter((_, i) => i !== Number(index));
        scan.doc = withTotals({ ...scan.doc, recognised_items: items });
        scan.edited = true;
        send(res, 200, scan.doc);
      },
    },
  ],
  [
    /^\/meals\/recognitions\/([0-9a-f]{24})\/confirm$/,
    {
      POST: async (req, res, [id]) => {
        const scan = ownScan(req, id);
        const log = confirmScan(scan, await readJson(req));
        nutritionLogs.push(log);
        scans.delete(id);
        send(res, 201, log);
      },
    },
  ],
];

const routes: Record<string, Partial<Record<string, Handler>>> = {
  '/health': {
    GET: (_req, res) => send(res, 200, { status: 'ok', postgres: 'ok', mongo: 'ok', version: 'mock' } satisfies Schemas['Health']),
  },
  '/auth/register': { POST: register },
  '/auth/login': { POST: login },
  '/auth/refresh': { POST: refresh },
  '/auth/logout': { POST: logout },
  '/users/me': { GET: (req, res) => send(res, 200, publicUser(currentUser(req))) },
  '/users/me/profile': { GET: getProfile, PUT: putProfile },
  '/users/me/injuries': {
    GET: (req, res) => send(res, 200, injuries.get(currentUser(req).id) ?? []),
    POST: createInjury,
  },
  '/users/me/allergies': {
    GET: (req, res) => {
      const ids = userAllergens.get(currentUser(req).id) ?? [];
      send(res, 200, allergens.filter((a) => ids.includes(a.id)));
    },
    PUT: putAllergies,
  },
  '/injury-types': { GET: (req, res) => sendReference(req, res, injuryTypes) },
  '/allergens': { GET: (req, res) => sendReference(req, res, allergens) },
  '/muscle-groups': { GET: (req, res) => sendReference(req, res, muscleGroups) },
  '/nutrition/targets': { GET: nutritionTargets },
  '/foods': { GET: listFoods },
  '/meals/recognitions': { POST: createRecognition },
};

/** A route with ids in the path: its handler for the method and the captured ids */
function matchPattern(path: string, method: string): { handler?: ParamHandler; params: string[] } | undefined {
  for (const [pattern, handlers] of patternRoutes) {
    const found = pattern.exec(path);
    if (found) {
      return { handler: handlers[method], params: found.slice(1) };
    }
  }
  return undefined;
}

// ---------------------------------------------------------------- server

const server = createServer(async (req, res) => {
  // Lets the Expo web version call the mock from the browser
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Headers', 'Authorization, Content-Type');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, PATCH, DELETE, OPTIONS');
  if (req.method === 'OPTIONS') {
    send(res, 204);
    return;
  }

  const path = new URL(req.url ?? '/', 'http://mock').pathname;
  const local = path.startsWith(PREFIX) ? path.slice(PREFIX.length) : '';
  const method = req.method ?? 'GET';
  const route = routes[local];
  const pattern = route ? undefined : matchPattern(local, method);
  try {
    if (!route && !pattern) {
      throw new HttpError(404, 'not_found', `No mock for ${path}`);
    }
    const handler = route?.[method];
    if (route && handler) {
      await handler(req, res);
    } else if (pattern?.handler) {
      await pattern.handler(req, res, pattern.params);
    } else {
      throw new HttpError(405, 'method_not_allowed', 'Method not allowed');
    }
  } catch (error) {
    if (error instanceof HttpError) {
      send(res, error.status, { code: error.code, message: error.message, details: error.details } satisfies Schemas['Error']);
    } else {
      console.error(error);
      send(res, 500, { code: 'internal_error', message: 'Mock server error', details: [] } satisfies Schemas['Error']);
    }
  }
  console.log(`${req.method} ${path} -> ${res.statusCode}`);
});

server.listen(PORT, () => {
  console.log(`FitPlan mock API on http://localhost:${PORT}${PREFIX} (Android emulator: http://10.0.2.2:${PORT}${PREFIX})`);
});
