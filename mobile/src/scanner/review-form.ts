import type { Recognition, RecognisedItem } from '@/scanner/scanner-api';

// RecognitionItemInput / RecognitionItemPatch: grams > 0, at most 99999.9
const MAX_GRAMS = 99999.9;

/** Error text for typed grams, or null when they can be sent */
export function checkGrams(text: string): string | null {
  const value = text.trim().replace(',', '.');
  if (!/^\d+(\.\d)?$/.test(value)) {
    return 'Enter the grams, at most 1 decimal.';
  }
  const grams = Number(value);
  if (grams <= 0 || grams > MAX_GRAMS) {
    return `Enter from 0.1 to ${MAX_GRAMS} g.`;
  }
  return null;
}

export const parseGrams = (text: string) => Number(text.trim().replace(',', '.'));

/** "grilled chicken" -> "Grilled chicken" */
export const itemName = (item: RecognisedItem) => item.name.charAt(0).toUpperCase() + item.name.slice(1);

/** Products that share an allergen with the user, shown before saving (M-15 Done) */
export function allergyItems(recognition: Recognition): string[] {
  return recognition.recognised_items.filter((item) => item.allergy_warning).map(itemName);
}

/** Short labels under a product; each comes with an icon on the screen, never colour alone */
export function itemFlags(item: RecognisedItem): ('pick' | 'allergen' | 'unsure')[] {
  const flags: ('pick' | 'allergen' | 'unsure')[] = [];
  if (item.food_item_id === null) flags.push('pick');
  if (item.allergy_warning) flags.push('allergen');
  if (item.low_confidence) flags.push('unsure');
  return flags;
}
