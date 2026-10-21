@REQ-HEXO7-001
Feature: Table of contents helper
  The toc helper shall parse all heading tags (h1 to h6) in the content and return a table of contents as text; content without heading tags gives an empty table of contents.

  @SCN-HEXO7-001-01 @type:edge
  Scenario: Content without headings
    Given the content "<p>No headings here</p>"
    When the table of contents is made
    Then the table of contents is ""

  @SCN-HEXO7-001-02 @type:positive
  Scenario: Content with one heading
    Given the content "<h1 id='intro'>Intro</h1>"
    When the table of contents is made
    Then the table of contents is returned as text
