// @requirement REQ-EXPRESS-004
const utils = require('../../subject-src/lib/utils');

describe('[REQ-EXPRESS-004] Proxy trust', () => {
  test("[SCN-EXPRESS-004-01][TST-EXPRESS-004-01-01] Trust all proxies with true :: setting true", () => {
    expect(utils.compileTrust(true)('10.0.0.1', 7)).toBe(true);
  });

  test.each([
    ['TST-EXPRESS-004-02-01', 0, true],
    ['TST-EXPRESS-004-02-02', 5, false],
  ])('[SCN-EXPRESS-004-02][%s] Trust a number of hops :: hops 2, hop %i -> %s', (_id, hop, trusted) => {
    expect(utils.compileTrust(2)('10.0.0.1', hop)).toBe(trusted);
  });

  test("[SCN-EXPRESS-004-03][TST-EXPRESS-004-03-01] Trust a list of addresses :: list '127.0.0.1, 10.0.0.1'", () => {
    const trust = utils.compileTrust('127.0.0.1, 10.0.0.1');
    expect(trust('10.0.0.1', 0)).toBe(true);
  });
});
