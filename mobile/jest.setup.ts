// Native modules do not exist in Jest; their official in-memory mocks replace them
jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);
jest.mock('react-native-safe-area-context', () => require('react-native-safe-area-context/jest/mock').default);
// Icon fonts cannot be loaded in Jest; a plain element stands in for each icon
jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
