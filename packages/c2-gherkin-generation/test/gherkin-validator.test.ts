
import { describe, expect, test } from 'vitest';
import { validateGherkin } from '../src/gherkin-validator.js';

describe('validateGherkin', () => {
  test('accepts a valid feature with a scenario', () => {
    const feature = `
Feature: User registration

  Scenario: Register a valid user
    Given a valid registration request
    When the user submits the request
    Then the registration succeeds
`;

    expect(validateGherkin(feature).valid).toBe(true);
  });

  test('rejects a document without a Feature declaration', () => {
    const feature = `
Scenario: Register a valid user
  Given a valid registration request
  When the user submits the request
  Then the registration succeeds
`;

    const result = validateGherkin(feature);

    expect(result.valid).toBe(false);
    expect(result.error).toBeTruthy();
  });

  test('rejects invalid Gherkin syntax', () => {
    const feature = `
Feature: User registration

  Scenario: Register a valid user
    Given a valid registration request
    When
    Then the registration succeeds
`;

    expect(validateGherkin(feature).valid).toBe(false);
  });
});
