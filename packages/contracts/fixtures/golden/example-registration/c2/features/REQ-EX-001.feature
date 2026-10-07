@REQ-EX-001
Feature: User registration age limit
  The system shall register a user only if the user's age is from 18 to 65 years inclusive,
  and shall reject any other age with a validation error.

  @SCN-EX-001-01 @type:positive
  Scenario: Register a user with a valid age
    Given the user repository is available
    When a user registers with age 30 and email "amal@example.com"
    Then the user is saved with age 30

  @SCN-EX-001-02 @type:boundary
  Scenario Outline: Age at and around the limits
    Given the user repository is available
    When a user registers with age <age> and email "test@example.com"
    Then the registration result is "<result>"

    Examples:
      | age | result   |
      | 17  | rejected |
      | 18  | accepted |
      | 19  | accepted |
      | 64  | accepted |
      | 65  | accepted |
      | 66  | rejected |
