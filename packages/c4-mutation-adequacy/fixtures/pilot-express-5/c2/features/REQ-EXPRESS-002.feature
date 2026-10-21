@REQ-EXPRESS-002
Feature: Media type normalisation
  The system shall convert a short type name such as 'html' to its full MIME type, and shall split a full type into its value, quality and parameters.

  @SCN-EXPRESS-002-01 @type:positive
  Scenario: Expand a short type name
    Given the type "html"
    When the type is normalized
    Then the value is "text/html" with no parameters

  @SCN-EXPRESS-002-02 @type:positive
  Scenario: Parse the quality of a full type
    Given the type "text/html; q=0.5"
    When the type is normalized
    Then the value is "text/html" and the quality is 0.5

  @SCN-EXPRESS-002-03 @type:positive
  Scenario: Normalize a list of types
    Given the types "html" and "json"
    When the types are normalized
    Then 2 normalized types are returned
