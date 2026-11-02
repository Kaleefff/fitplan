/**
 * Mock of the FitPlan Pro API for app development (M-01).
 * Implements the operations the app uses so far, keeps data in memory and types every
 * answer with the schemas generated from docs/api/openapi.yaml, so `npm run typecheck`
 * fails when the mock drifts from the contract.
 *
 * Run: `npm run mock` (port 4010, change with MOCK_PORT); data is lost on restart.
 * Business rules are simplified; the real backend is the reference.
 */
import { randomBytes } from 'node:crypto';
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
};

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
  const route = path.startsWith(PREFIX) ? routes[path.slice(PREFIX.length)] : undefined;
  const handler = route?.[req.method ?? 'GET'];
  try {
    if (!route) {
      throw new HttpError(404, 'not_found', `No mock for ${path}`);
    }
    if (!handler) {
      throw new HttpError(405, 'method_not_allowed', 'Method not allowed');
    }
    await handler(req, res);
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
