// @requirement REQ-EXPRESS-003
const utils = require('../../subject-src/lib/utils');

describe('[REQ-EXPRESS-003] ETag function selection', () => {
  test.each([
    ['TST-EXPRESS-003-01-01', true, 'weak'],
    ['TST-EXPRESS-003-01-02', 'weak', 'weak'],
    ['TST-EXPRESS-003-01-03', false, 'none'],
  ])('[SCN-EXPRESS-003-01][%s] Select the ETag function from the setting :: setting %s -> %s', (_id, setting, kind) => {
    const fn = utils.compileETag(setting);
    if (kind === 'none') expect(fn).toBeUndefined();
    else expect(fn('hello')).toMatch(/^W\//);
  });

  test("[SCN-EXPRESS-003-02][TST-EXPRESS-003-02-01] Reject an unknown ETag setting :: setting 'bogus'", () => {
    expect(() => utils.compileETag('bogus')).toThrow(TypeError);
  });
});
