// @requirement REQ-EX-001
// Generated-style golden fixture for C3 -> C4. Title format is part of the contract:
//   describe: "[REQ-...] <feature name>"
//   test:     "[SCN-...][TST-...] <scenario name> :: <case>"
jest.mock('../../subject-src/src/userRepository');
const userRepository = require('../../subject-src/src/userRepository');
const { registerUser, ValidationError } = require('../../subject-src/src/registration');

describe('[REQ-EX-001] User registration age limit', () => {
  beforeEach(() => {
    userRepository.save.mockReset();
    userRepository.save.mockImplementation((u) => ({ id: 'u1', ...u }));
  });

  test('[SCN-EX-001-01][TST-EX-001-01-01] Register a user with a valid age :: age 30', () => {
    const saved = registerUser({ age: 30, email: 'amal@example.com' });
    expect(userRepository.save).toHaveBeenCalledWith({ age: 30, email: 'amal@example.com' });
    expect(saved.age).toBe(30);
  });

  test.each([
    ['TST-EX-001-02-01', 17, 'rejected'],
    ['TST-EX-001-02-02', 18, 'accepted'],
    ['TST-EX-001-02-03', 19, 'accepted'],
    ['TST-EX-001-02-04', 64, 'accepted'],
    ['TST-EX-001-02-05', 65, 'accepted'],
    ['TST-EX-001-02-06', 66, 'rejected'],
  ])('[SCN-EX-001-02][%s] Age at and around the limits :: age %i -> %s', (_id, age, result) => {
    if (result === 'rejected') {
      expect(() => registerUser({ age, email: 'test@example.com' })).toThrow(ValidationError);
      expect(userRepository.save).not.toHaveBeenCalled();
    } else {
      expect(() => registerUser({ age, email: 'test@example.com' })).not.toThrow();
      expect(userRepository.save).toHaveBeenCalledTimes(1);
    }
  });
});
