import { PlaceholderScreen } from '@/components/placeholder-screen';

export default function StatsScreen() {
  return (
    <PlaceholderScreen
      module="stats"
      upcoming={[
        'Week, month and 3-month summaries',
        'Weight, workouts and calorie charts',
        'Goal date prediction',
        'Weekly and monthly reports',
      ]}
    />
  );
}
