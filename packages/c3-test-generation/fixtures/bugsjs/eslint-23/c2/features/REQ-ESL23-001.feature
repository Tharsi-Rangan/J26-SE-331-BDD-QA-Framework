@REQ-ESL23-001
Feature: File pattern resolution
  The system shall turn each directory pattern into a glob that matches the files with the accepted extensions, keep every pattern that is not a directory as it is, and write all path separators in POSIX style (/).

  @SCN-ESL23-001-01 @type:positive
  Scenario: Keep a file pattern unchanged
    Given the file patterns "src/app.js"
    When the file patterns are resolved
    Then the resolved patterns are "src/app.js"

  @SCN-ESL23-001-02 @type:positive
  Scenario: Write path separators in POSIX style
    Given the file patterns "src\app.js"
    When the file patterns are resolved
    Then the resolved patterns are "src/app.js"
