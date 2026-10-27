import createClient from 'openapi-fetch';

import { apiErrorFromResponse, networkError } from '@/api/errors';
import type { paths } from '@/api/schema';
import { config } from '@/config';

export type Transport = (request: Request) => Promise<Response>;

let transport: Transport = (request) => fetch(request);

/** Replaces how requests are sent; the auth session uses it to add tokens */
export function setTransport(next: Transport) {
  transport = next;
}

/** Typed client for every operation of docs/api/openapi.yaml */
export const api = createClient<paths>({
  baseUrl: config.apiUrl,
  fetch: (request) => transport(request),
});

type ClientResult<T> = { data?: T; error?: unknown; response: Response };

/**
 * Returns the data of a successful answer and throws ApiError otherwise.
 * Usage: `const user = await unwrap(api.GET('/users/me'));`
 */
export async function unwrap<T>(call: Promise<ClientResult<T>>): Promise<T> {
  let result: ClientResult<T>;
  try {
    result = await call;
  } catch (cause) {
    throw networkError(cause);
  }
  if (result.response.ok) {
    return result.data as T;
  }
  throw apiErrorFromResponse(result.response, result.error);
}
