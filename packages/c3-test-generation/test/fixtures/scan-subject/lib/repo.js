'use strict';
module.exports = {
  /** @param {{ name: string }} user @returns {{ id: string, name: string }} */
  save(user) {
    throw new Error('real database not available');
  },
};
