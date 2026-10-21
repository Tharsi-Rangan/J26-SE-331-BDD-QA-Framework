// @requirement REQ-EXPRESS-002
const utils = require('../../subject-src/lib/utils');

describe('[REQ-EXPRESS-002] Media type normalisation', () => {
  test("[SCN-EXPRESS-002-01][TST-EXPRESS-002-01-01] Expand a short type name :: type 'html'", () => {
    expect(utils.normalizeType('html')).toEqual({ value: 'text/html', params: {} });
  });

  test("[SCN-EXPRESS-002-02][TST-EXPRESS-002-02-01] Parse the quality of a full type :: type 'text/html; q=0.5'", () => {
    const r = utils.normalizeType('text/html; q=0.5');
    expect(r.value).toBe('text/html');
    expect(r.quality).toBeDefined();
  });

  test("[SCN-EXPRESS-002-03][TST-EXPRESS-002-03-01] Normalize a list of types :: types ['html', 'json']", () => {
    expect(utils.normalizeTypes(['html', 'json'])).toHaveLength(2);
  });

  test("[SCN-EXPRESS-002-04][TST-EXPRESS-002-04-01] Parse the parameters of a full type :: type 'text/html; charset=utf-8; q=0.5'", () => {
    expect(utils.normalizeType('text/html; charset=utf-8; q=0.5')).toEqual({
      value: 'text/html',
      quality: 0.5,
      params: { charset: 'utf-8' },
    });
  });
});
