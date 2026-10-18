// @requirement REQ-EXPRESS-001
const utils = require('../../subject-src/lib/utils');

describe('[REQ-EXPRESS-001] Absolute path detection', () => {
  test("[SCN-EXPRESS-001-01][TST-EXPRESS-001-01-01] Detect absolute POSIX and Windows paths :: path '/home/user'", () => {
    expect(utils.isAbsolute('/home/user')).toBe(true);
  });

  test("[SCN-EXPRESS-001-01][TST-EXPRESS-001-01-02] Detect absolute POSIX and Windows paths :: path 'C:\\\\Users'", () => {
    expect(utils.isAbsolute('C:\\Users')).toBe(true);
  });

  test("[SCN-EXPRESS-001-02][TST-EXPRESS-001-02-01] Reject relative paths :: path 'foo/bar'", () => {
    expect(utils.isAbsolute('foo/bar')).toBeFalsy();
  });
});
