@REQ-EXPRESS-003
Feature: ETag function selection
  The system shall select the weak ETag function for true or 'weak', the strong ETag function for 'strong', no function for false, and shall reject any other value with a TypeError.

  @SCN-EXPRESS-003-01 @type:positive
  Scenario Outline: Select the ETag function from the setting
    Given the ETag setting <setting>
    When the ETag function is compiled
    Then the function is "<kind>"

    Examples:
      | setting | kind |
      | true | weak |
      | weak | weak |
      | false | none |

  @SCN-EXPRESS-003-02 @type:negative
  Scenario: Reject an unknown ETag setting
    Given the ETag setting "bogus"
    When the ETag function is compiled
    Then a TypeError is thrown
