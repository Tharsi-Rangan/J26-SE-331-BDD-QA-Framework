@REQ-EXPRESS-004
Feature: Proxy trust
  The system shall build a proxy trust function from true (trust all proxies), from a hop count n (trust the first n hops), from a comma-separated list of addresses, or from a function.

  @SCN-EXPRESS-004-01 @type:positive
  Scenario: Trust all proxies with true
    Given the trust setting true
    When the trust function is compiled
    Then every proxy is trusted

  @SCN-EXPRESS-004-02 @type:boundary
  Scenario Outline: Trust a number of hops
    Given the trust setting 2
    When hop <hop> is checked
    Then the trust result is <trusted>

    Examples:
      | hop | trusted |
      | 0 | true |
      | 5 | false |

  @SCN-EXPRESS-004-03 @type:positive
  Scenario: Trust a list of addresses
    Given the trust setting "127.0.0.1, 10.0.0.1"
    When the address "10.0.0.1" is checked
    Then the address is trusted
