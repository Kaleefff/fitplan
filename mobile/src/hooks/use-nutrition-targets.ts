import { useCallback, useEffect, useState } from 'react';

import { api, unwrap } from '@/api/client';
import { toApiError, userMessage } from '@/api/errors';
import type { components } from '@/api/schema';

type NutritionTargets = components['schemas']['NutritionTargets'];

export type TargetsState =
  | { status: 'loading' }
  | { status: 'ready'; targets: NutritionTargets }
  /** 404: the server has no profile for the user */
  | { status: 'unavailable' }
  | { status: 'error'; message: string };

async function fetchTargets(): Promise<TargetsState> {
  try {
    return { status: 'ready', targets: await unwrap(api.GET('/nutrition/targets')) };
  } catch (error) {
    const apiError = toApiError(error);
    return apiError.status === 404 ? { status: 'unavailable' } : { status: 'error', message: userMessage(apiError) };
  }
}

/** GET /nutrition/targets (FR-P4, FR-P5); loads again when `reloadKey` changes, e.g. after a profile edit */
export function useNutritionTargets(reloadKey: string | undefined) {
  const [state, setState] = useState<TargetsState>({ status: 'loading' });

  useEffect(() => {
    let active = true;
    fetchTargets().then((next) => {
      if (active) {
        setState(next);
      }
    });
    return () => {
      active = false;
    };
  }, [reloadKey]);

  const retry = useCallback(() => {
    setState({ status: 'loading' });
    fetchTargets().then(setState);
  }, []);

  return { state, retry };
}
