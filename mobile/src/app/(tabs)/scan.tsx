import { PlaceholderScreen } from '@/components/placeholder-screen';

export default function ScanScreen() {
  return (
    <PlaceholderScreen
      module="scan"
      upcoming={[
        'Take a meal photo or pick one from the gallery',
        'Review recognised products and correct the grams',
        'Allergy warnings before saving',
        "Today's nutrition: calories, protein, carbs, fats",
      ]}
    />
  );
}
