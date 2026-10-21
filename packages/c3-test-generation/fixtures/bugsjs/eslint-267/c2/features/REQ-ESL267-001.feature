@REQ-ESL267-001
Feature: Configuration merging
  When a derived configuration is merged over a base configuration, the system shall add the keys that are missing in the base, let the derived values take priority, and, when the derived configuration changes only the severity of an inherited rule, keep the inherited rule options.

  @SCN-ESL267-001-01 @type:positive
  Scenario: Keep rule options when only the severity changes
    Given the base configuration {"rules": {"eqeqeq": ["error", "allow-null"]}}
    And the derived configuration {"rules": {"eqeqeq": "warn"}}
    When the configurations are merged
    Then the merged rules eqeqeq setting is ["warn", "allow-null"]

  @SCN-ESL267-001-02 @type:positive
  Scenario: Add a key that the base does not have
    Given the base configuration {}
    And the derived configuration {"globals": {"foo": true}}
    When the configurations are merged
    Then the merged globals are {"foo": true}

  @SCN-ESL267-001-03 @type:positive
  Scenario: Let the derived value take priority
    Given the base configuration {"env": {"browser": true}}
    And the derived configuration {"env": {"browser": false}}
    When the configurations are merged
    Then the merged env browser setting is false
