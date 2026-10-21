@REQ-EXPRESS-001
Feature: Absolute path detection
  The system shall treat a path as absolute when it starts with '/', when it starts with a drive letter followed by ':' and '\', or when it starts with '\\'.

  @SCN-EXPRESS-001-01 @type:positive
  Scenario: Detect absolute POSIX and Windows paths
    Given the path "/home/user"
    When the path is checked
    Then the path is absolute

  @SCN-EXPRESS-001-02 @type:negative
  Scenario: Reject relative paths
    Given the path "foo/bar"
    When the path is checked
    Then the path is not absolute
