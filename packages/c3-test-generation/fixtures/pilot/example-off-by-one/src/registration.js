// C3-14 control subject: the example with a planted off-by-one bug (age > 64 instead of age > 65).
// Not a BugsJS bug. The correct version is packages/contracts/fixtures/golden/example-registration/subject-src.
const userRepository = require('./userRepository');

class ValidationError extends Error {}

function registerUser({ age, email }) {
  if (age < 18 || age > 64) {
    throw new ValidationError('age out of range');
  }
  return userRepository.save({ age, email });
}

module.exports = { registerUser, ValidationError };
