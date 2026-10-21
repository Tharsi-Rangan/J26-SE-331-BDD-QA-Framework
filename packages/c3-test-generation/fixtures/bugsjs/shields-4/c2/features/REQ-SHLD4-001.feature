@REQ-SHLD4-001
Feature: Badge making
  The badge maker shall make a badge from a format object with text (the textual information shown, in order), an optional colorscheme, and a template from the templates folder (flat, flat-square, plastic, social or for-the-badge), and shall return the badge as SVG text.

  @SCN-SHLD4-001-01 @type:positive
  Scenario Outline: Make a badge in each template
    Given the badge text "build" and "passed"
    And the template "<template>"
    When the badge is made
    Then the badge is returned as text

    Examples:
      | template |
      | flat |
      | plastic |
      | for-the-badge |
