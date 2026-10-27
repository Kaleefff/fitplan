import type { components } from '@/api/schema';

export type ErrorBody = components['schemas']['Error'];
export type ErrorDetail = components['schemas']['ErrorDetail'];

/** Codes the app adds for failures that never reached the server's error model */
export type ClientErrorCode = 'network_error' | 'unexpected_response';

// One error type for every failed call, so screens handle errors the same way
export class ApiError extends Error {
  /** HTTP status; 0 when the request never got an answer */
  readonly status: number;
  /** Contract code (`validation_error`, `invalid_credentials`, …) or a ClientErrorCode */
  readonly code: string;
  readonly details: ErrorDetail[];
  /** From the Retry-After header of 429 and 503 answers */
  readonly retryAfterSeconds: number | null;

  constructor(
    status: number,
    code: string,
    message: string,
    details: ErrorDetail[] = [],
    retryAfterSeconds: number | null = null,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

export function isErrorBody(value: unknown): value is ErrorBody {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const body = value as Record<string, unknown>;
  return typeof body.code === 'string' && typeof body.message === 'string';
}

function parseRetryAfter(response: Response): number | null {
  const header = response.headers.get('Retry-After');
  const seconds = header === null ? NaN : Number(header);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}

/** Builds an ApiError from a non-2xx answer and its parsed JSON body (if any) */
export function apiErrorFromResponse(response: Response, body: unknown): ApiError {
  const retryAfter = parseRetryAfter(response);
  if (isErrorBody(body)) {
    return new ApiError(response.status, body.code, body.message, body.details ?? [], retryAfter);
  }
  return new ApiError(
    response.status,
    'unexpected_response',
    `The server answered ${response.status} without the expected error body.`,
    [],
    retryAfter,
  );
}

export function networkError(cause: unknown): ApiError {
  const error = new ApiError(0, 'network_error', 'The server could not be reached.');
  error.cause = cause;
  return error;
}

export function toApiError(error: unknown): ApiError {
  return error instanceof ApiError ? error : networkError(error);
}

// "body.email" -> "email", "body.sets.0.reps" -> "sets.0.reps"
function formFieldName(path: string): string {
  return path.replace(/^(body|query|path)\./, '');
}

// Pydantic prefixes custom validator messages with "Value error, "
function cleanMessage(message: string): string {
  return message.replace(/^Value error, /, '');
}

/** First message per form field, from the `details[]` of a 422 answer */
export function fieldErrors(error: ApiError): Record<string, string> {
  const result: Record<string, string> = {};
  for (const detail of error.details) {
    if (!detail.field) {
      continue;
    }
    const name = formFieldName(detail.field);
    if (!(name in result)) {
      result[name] = cleanMessage(detail.message);
    }
  }
  return result;
}

/** Text to show the user when the error is not tied to one field */
export function userMessage(error: ApiError): string {
  switch (error.code) {
    case 'network_error':
      return 'Cannot reach the server. Check your internet connection and try again.';
    case 'rate_limited':
      return error.retryAfterSeconds !== null
        ? `Too many attempts. Try again in ${error.retryAfterSeconds} s.`
        : 'Too many attempts. Try again in a moment.';
    case 'unauthorized':
      return 'Your session has expired. Please sign in again.';
    case 'internal_error':
    case 'unexpected_response':
      return 'Something went wrong on the server. Please try again.';
    default:
      return cleanMessage(error.message);
  }
}
