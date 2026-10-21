'use strict';
const { format } = require('util');

// A nameless module export, like ESLint's lib/formatters/junit.js (BugsJS eslint-197 / eslint-209).
module.exports = function (results) {
  return format('%d result(s)', results.length);
};
