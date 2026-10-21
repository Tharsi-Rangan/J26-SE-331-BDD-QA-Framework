@REQ-ESL22-001
Feature: Rule severity validation
  The system shall accept a rule severity of "off" or 0, "warn" or 1, and "error" or 2, given alone or as the first item of an options array, and shall reject any other severity with an Error. The first item of an options array is always the rule severity, a number or a string.

  @SCN-ESL22-001-01 @type:positive
  Scenario Outline: Accept a valid rule severity
    Given the rule "quotes" with the setting <setting>
    When the rule configuration is validated
    Then the configuration is accepted without an error

    Examples:
      | setting |
      | off |
      | warn |
      | error |
      | 0 |
      | 1 |
      | 2 |

  @SCN-ESL22-001-02 @type:negative
  Scenario Outline: Reject a severity that is not allowed
    Given the rule "quotes" with the setting <setting>
    When the rule configuration is validated
    Then an Error is thrown

    Examples:
      | setting |
      | warning |
      | 3 |

  @SCN-ESL22-001-03 @type:negative
  Scenario: Reject a list given as the severity
    Given the rule "quotes" with the setting [["error"], "double"]
    When the rule configuration is validated
    Then an Error is thrown
