@REQ-ESL273-001
Feature: Rule configuration generation
  The system shall generate the valid configurations of a rule from its options schema: the error severity 2 on its own, and, for an option with a list of allowed values, one configuration [2, value] for each value.

  @SCN-ESL273-001-01 @type:edge
  Scenario: Rule without options
    Given the options schema []
    When the rule configurations are generated
    Then the configurations are [2]

  @SCN-ESL273-001-02 @type:positive
  Scenario: Rule with one option of allowed values
    Given the options schema [{"enum": ["always", "never"]}]
    When the rule configurations are generated
    Then the configurations are [2, [2, "always"], [2, "never"]]
