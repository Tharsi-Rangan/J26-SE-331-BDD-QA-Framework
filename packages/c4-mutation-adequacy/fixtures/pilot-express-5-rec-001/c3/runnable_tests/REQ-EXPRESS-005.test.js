// @requirement REQ-EXPRESS-005
const utils = require('../../subject-src/lib/utils');

describe('[REQ-EXPRESS-005] Content-Type charset', () => {
  test("[SCN-EXPRESS-005-01][TST-EXPRESS-005-01-01] Set the charset of a type :: type 'text/html', charset 'utf-8'", () => {
    expect(utils.setCharset('text/html', 'utf-8')).toBe('text/html; charset=utf-8');
  });

  test("[SCN-EXPRESS-005-02][TST-EXPRESS-005-02-01] Keep the type when the charset is missing :: type 'text/html', no charset", () => {
    expect(utils.setCharset('text/html')).toBe('text/html');
  });
});
