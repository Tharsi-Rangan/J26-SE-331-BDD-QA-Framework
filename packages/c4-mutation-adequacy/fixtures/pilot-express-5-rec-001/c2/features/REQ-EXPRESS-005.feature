@REQ-EXPRESS-005
Feature: Content-Type charset
  The system shall set the charset parameter of a Content-Type value, and shall return the type unchanged when the type or the charset is missing.

  @SCN-EXPRESS-005-01 @type:positive
  Scenario: Set the charset of a type
    Given the type "text/html" and the charset "utf-8"
    When the charset is set
    Then the type is "text/html; charset=utf-8"

  @SCN-EXPRESS-005-02 @type:edge
  Scenario: Keep the type when the charset is missing
    Given the type "text/html" and no charset
    When the charset is set
    Then the type is "text/html"
