'use strict';
// Patterns from the pilots: plain, destructured, property and called requires.
const fs = require('fs');
const path = require('path');
const { join } = require('node:path');
const repo = require('./repo');
const basename = require('path').basename; // imported but never used
var debug = require('debug')('demo'); // runs while the module loads
const helpers = require('./helpers'); // resolves to helpers/index.js
const limits = require(path.join(__dirname, 'limits.json'));
const plugin = require(process.env.PLUGIN_NAME); // computed at runtime: skipped with a warning

const files = fs.readdirSync(join(__dirname, 'data'));
files.forEach(function (f) {
  debug('found ' + f);
});

// Uses no dependency at all (like Express-5's isAbsolute).
exports.isAbsolute = function (p) {
  if ('/' === p[0]) return true;
  return p[1] === ':' && p[2] === '\\';
};

// Uses an internal module and a global clock.
exports.saveUser = function (user) {
  const stamped = Object.assign({ createdAt: Date.now() }, user);
  return repo.save(stamped);
};

// Reaches dependencies through a local helper and through another export.
function readConfig(name) {
  return JSON.parse(fs.readFileSync(join('/etc', name), 'utf8'));
}
exports.loadConfig = function (name) {
  if (name.length > limits.maxName) throw new Error('name too long');
  return readConfig(name);
};
exports.reloadConfig = function (name) {
  return exports.loadConfig(name);
};

// Global members: Math.random counts, Math.floor does not; a local `process` is not the global.
exports.pickId = function (process) {
  const n = Math.floor(Math.random() * 100);
  return process.prefix + helpers.pad(n);
};

// Inline require inside a function.
exports.hash = function (s) {
  return require('crypto').createHash('sha1').update(s).digest('hex');
};
