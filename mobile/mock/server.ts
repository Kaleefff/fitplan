/**
 * Mock of the FitPlan Pro API for app development (M-01).
 * Implements the account operations the app uses (register, login, refresh, logout,
 * GET /users/me), keeps data in memory and types every
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

// ---------------------------------------------------------------- in-memory state

type StoredUser = Schemas['User'] & { password: string };

const users: StoredUser[] = [];
const accessTokens = new Map<string, { userId: number; expiresAt: number }>();
const refreshTokens = new Map<string, number>();

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

const routes: Record<string, Partial<Record<string, Handler>>> = {
  '/health': {
    GET: (_req, res) => send(res, 200, { status: 'ok', postgres: 'ok', mongo: 'ok', version: 'mock' } satisfies Schemas['Health']),
  },
  '/auth/register': { POST: register },
  '/auth/login': { POST: login },
  '/auth/refresh': { POST: refresh },
  '/auth/logout': { POST: logout },
  '/users/me': { GET: (req, res) => send(res, 200, publicUser(currentUser(req))) },
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
