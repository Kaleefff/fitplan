import { PlaceholderScreen } from '@/components/placeholder-screen';

export default function DietScreen() {
  return (
    <PlaceholderScreen
      module="diet"
      upcoming={[
        'TDEE and daily calorie target',
        'Protein, carbs and fat targets',
        'Meals of the day with products and grams',
        'Regenerate or accept the plan',
      ]}
    />
  );
}
