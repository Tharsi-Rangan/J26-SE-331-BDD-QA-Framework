'use strict';
const missing = require('./does-not-exist');
const { format } = require('util');

function makeBadge(text) {
  return format('[%s]', text) + missing.suffix;
}

module.exports = makeBadge;
module.exports.version = '1.0.0';
