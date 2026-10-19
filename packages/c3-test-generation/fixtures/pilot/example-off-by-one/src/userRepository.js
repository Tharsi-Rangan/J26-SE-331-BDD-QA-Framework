// Pretend database access: C3's rules should decide to MOCK this.
module.exports = {
  save(user) {
    throw new Error('real database not available in tests');
  },
};
