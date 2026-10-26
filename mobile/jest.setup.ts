// Native modules do not exist in Jest; their official in-memory mocks replace them
jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);
