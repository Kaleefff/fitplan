import { useEffect, useState } from 'react';

import { toApiError, userMessage } from '@/api/errors';
import { searchFoods, type FoodItem } from '@/diet/diet-api';

/** Search starts from this many letters, a short wait after the last key */
export const MIN_SEARCH = 2;
const SEARCH_DELAY_MS = 300;

export type Search =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; items: FoodItem[] };

/** Results of the last finished search; idle and loading follow from the text */
type Result = { query: string; items: FoodItem[] } | { query: string; error: string };

/** Food database search (FR-P8) for the text typed so far */
export function useFoodSearch(text: string): Search {
  const [result, setResult] = useState<Result | null>(null);
  const query = text.trim();
  useEffect(() => {
    if (query.length < MIN_SEARCH) {
      return;
    }
    let current = true;
    const timer = setTimeout(() => {
      searchFoods(query)
        .then((items) => current && setResult({ query, items }))
        .catch((error) => current && setResult({ query, error: userMessage(toApiError(error)) }));
    }, SEARCH_DELAY_MS);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [query]);

  if (query.length < MIN_SEARCH) return { status: 'idle' };
  if (result?.query !== query) return { status: 'loading' };
  return 'error' in result ? { status: 'error', message: result.error } : { status: 'ready', items: result.items };
}
