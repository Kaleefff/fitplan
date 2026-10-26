import { PlaceholderScreen } from '@/components/placeholder-screen';

export default function TrainingScreen() {
  return (
    <PlaceholderScreen
      module="training"
      upcoming={[
        'Generate a plan from goal, training days, level and equipment',
        'Sessions for each training day with sets and reps',
        'Swap an exercise for an alternative',
        'Log a workout and rate it with RPE',
      ]}
    />
  );
}
