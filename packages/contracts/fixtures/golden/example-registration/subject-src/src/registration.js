// Teaching example subject (stands in for a BugsJS module).
const userRepository = require('./userRepository');

class ValidationError extends Error {}

function registerUser({ age, email }) {
  if (age < 18 || age > 65) {
    throw new ValidationError('age out of range');
  }
  return userRepository.save({ age, email });
}

module.exports = { registerUser, ValidationError };
