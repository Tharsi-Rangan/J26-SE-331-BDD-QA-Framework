@REQ-ESL209-001
Feature: JUnit report
  The junit formatter shall turn the lint results (one result per linted file, each with its messages) into a JUnit XML report, returned as text, with one testsuite per linted file.

  @SCN-ESL209-001-01 @type:positive
  Scenario: Report a file with one problem
    Given the lint results [{"filePath": "a.js", "messages": [{"ruleId": "semi", "severity": 2, "message": "Missing semicolon.", "line": 1, "column": 10}]}]
    When the junit report is formatted
    Then the report is returned as text

  @SCN-ESL209-001-02 @type:edge
  Scenario: Report a file without problems
    Given the lint results [{"filePath": "b.js", "messages": []}]
    When the junit report is formatted
    Then the report is returned as text
