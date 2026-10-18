# Annotation packet: Express-5 pilot (C4-08)

Read `docs/trace-annotation-guideline.md` first. Label every survivor in section 5.

## 1. Requirements and scenarios

### REQ-EXPRESS-001: Absolute path detection

The system shall treat a path as absolute when it starts with '/', when it starts with a drive letter followed by ':' and '\', or when it starts with '\\'.

```gherkin
@REQ-EXPRESS-001
Feature: Absolute path detection
  The system shall treat a path as absolute when it starts with '/', when it starts with a drive letter followed by ':' and '\', or when it starts with '\\'.

  @SCN-EXPRESS-001-01 @type:positive
  Scenario: Detect absolute POSIX and Windows paths
    Given the path "/home/user"
    When the path is checked
    Then the path is absolute

  @SCN-EXPRESS-001-02 @type:negative
  Scenario: Reject relative paths
    Given the path "foo/bar"
    When the path is checked
    Then the path is not absolute
```

### REQ-EXPRESS-002: Media type normalisation

The system shall convert a short type name such as 'html' to its full MIME type, and shall split a full type into its value, quality and parameters.

```gherkin
@REQ-EXPRESS-002
Feature: Media type normalisation
  The system shall convert a short type name such as 'html' to its full MIME type, and shall split a full type into its value, quality and parameters.

  @SCN-EXPRESS-002-01 @type:positive
  Scenario: Expand a short type name
    Given the type "html"
    When the type is normalized
    Then the value is "text/html" with no parameters

  @SCN-EXPRESS-002-02 @type:positive
  Scenario: Parse the quality of a full type
    Given the type "text/html; q=0.5"
    When the type is normalized
    Then the value is "text/html" and the quality is 0.5

  @SCN-EXPRESS-002-03 @type:positive
  Scenario: Normalize a list of types
    Given the types "html" and "json"
    When the types are normalized
    Then 2 normalized types are returned
```

### REQ-EXPRESS-003: ETag function selection

The system shall select the weak ETag function for true or 'weak', the strong ETag function for 'strong', no function for false, and shall reject any other value with a TypeError.

```gherkin
@REQ-EXPRESS-003
Feature: ETag function selection
  The system shall select the weak ETag function for true or 'weak', the strong ETag function for 'strong', no function for false, and shall reject any other value with a TypeError.

  @SCN-EXPRESS-003-01 @type:positive
  Scenario Outline: Select the ETag function from the setting
    Given the ETag setting <setting>
    When the ETag function is compiled
    Then the function is "<kind>"

    Examples:
      | setting | kind |
      | true | weak |
      | weak | weak |
      | false | none |

  @SCN-EXPRESS-003-02 @type:negative
  Scenario: Reject an unknown ETag setting
    Given the ETag setting "bogus"
    When the ETag function is compiled
    Then a TypeError is thrown
```

### REQ-EXPRESS-004: Proxy trust

The system shall build a proxy trust function from true (trust all proxies), from a hop count n (trust the first n hops), from a comma-separated list of addresses, or from a function.

```gherkin
@REQ-EXPRESS-004
Feature: Proxy trust
  The system shall build a proxy trust function from true (trust all proxies), from a hop count n (trust the first n hops), from a comma-separated list of addresses, or from a function.

  @SCN-EXPRESS-004-01 @type:positive
  Scenario: Trust all proxies with true
    Given the trust setting true
    When the trust function is compiled
    Then every proxy is trusted

  @SCN-EXPRESS-004-02 @type:boundary
  Scenario Outline: Trust a number of hops
    Given the trust setting 2
    When hop <hop> is checked
    Then the trust result is <trusted>

    Examples:
      | hop | trusted |
      | 0 | true |
      | 5 | false |

  @SCN-EXPRESS-004-03 @type:positive
  Scenario: Trust a list of addresses
    Given the trust setting "127.0.0.1, 10.0.0.1"
    When the address "10.0.0.1" is checked
    Then the address is trusted
```

### REQ-EXPRESS-005: Content-Type charset

The system shall set the charset parameter of a Content-Type value, and shall return the type unchanged when the type or the charset is missing.

```gherkin
@REQ-EXPRESS-005
Feature: Content-Type charset
  The system shall set the charset parameter of a Content-Type value, and shall return the type unchanged when the type or the charset is missing.

  @SCN-EXPRESS-005-01 @type:positive
  Scenario: Set the charset of a type
    Given the type "text/html" and the charset "utf-8"
    When the charset is set
    Then the type is "text/html; charset=utf-8"

  @SCN-EXPRESS-005-02 @type:edge
  Scenario: Keep the type when the charset is missing
    Given the type "text/html" and no charset
    When the charset is set
    Then the type is "text/html"
```

## 2. Tests (C3 output)

### REQ-EXPRESS-001.test.js

```js
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
```

### REQ-EXPRESS-002.test.js

```js
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
});
```

### REQ-EXPRESS-003.test.js

```js
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
```

### REQ-EXPRESS-004.test.js

```js
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
```

### REQ-EXPRESS-005.test.js

```js
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
```

## 3. Module under test: `lib/utils.js` (with line numbers)

```js
   1  /*!
   2   * express
   3   * Copyright(c) 2009-2013 TJ Holowaychuk
   4   * Copyright(c) 2014-2015 Douglas Christopher Wilson
   5   * MIT Licensed
   6   */
   7  
   8  'use strict';
   9  
  10  /**
  11   * Module dependencies.
  12   * @api private
  13   */
  14  
  15  var contentDisposition = require('content-disposition');
  16  var contentType = require('content-type');
  17  var deprecate = require('depd')('express');
  18  var flatten = require('array-flatten');
  19  var mime = require('send').mime;
  20  var basename = require('path').basename;
  21  var etag = require('etag');
  22  var proxyaddr = require('proxy-addr');
  23  var qs = require('qs');
  24  var querystring = require('querystring');
  25  
  26  /**
  27   * Return strong ETag for `body`.
  28   *
  29   * @param {String|Buffer} body
  30   * @param {String} [encoding]
  31   * @return {String}
  32   * @api private
  33   */
  34  
  35  exports.etag = function (body, encoding) {
  36    var buf = !Buffer.isBuffer(body)
  37      ? new Buffer(body, encoding)
  38      : body;
  39  
  40    return etag(buf, {weak: false});
  41  };
  42  
  43  /**
  44   * Return weak ETag for `body`.
  45   *
  46   * @param {String|Buffer} body
  47   * @param {String} [encoding]
  48   * @return {String}
  49   * @api private
  50   */
  51  
  52  exports.wetag = function wetag(body, encoding){
  53    var buf = !Buffer.isBuffer(body)
  54      ? new Buffer(body, encoding)
  55      : body;
  56  
  57    return etag(buf, {weak: true});
  58  };
  59  
  60  /**
  61   * Check if `path` looks absolute.
  62   *
  63   * @param {String} path
  64   * @return {Boolean}
  65   * @api private
  66   */
  67  
  68  exports.isAbsolute = function(path){
  69    if ('/' === path[0]) return true;
  70    if (':' === path[1] && '\\' === path[2]) return true;
  71    if ('\\\\' === path.substring(0, 2)) return true; // Microsoft Azure absolute path
  72  };
  73  
  74  /**
  75   * Flatten the given `arr`.
  76   *
  77   * @param {Array} arr
  78   * @return {Array}
  79   * @api private
  80   */
  81  
  82  exports.flatten = deprecate.function(flatten,
  83    'utils.flatten: use array-flatten npm module instead');
  84  
  85  /**
  86   * Normalize the given `type`, for example "html" becomes "text/html".
  87   *
  88   * @param {String} type
  89   * @return {Object}
  90   * @api private
  91   */
  92  
  93  exports.normalizeType = function(type){
  94    return ~type.indexOf('/')
  95      ? acceptParams(type)
  96      : { value: mime.lookup(type), params: {} };
  97  };
  98  
  99  /**
 100   * Normalize `types`, for example "html" becomes "text/html".
 101   *
 102   * @param {Array} types
 103   * @return {Array}
 104   * @api private
 105   */
 106  
 107  exports.normalizeTypes = function(types){
 108    var ret = [];
 109  
 110    for (var i = 0; i < types.length; ++i) {
 111      ret.push(exports.normalizeType(types[i]));
 112    }
 113  
 114    return ret;
 115  };
 116  
 117  /**
 118   * Generate Content-Disposition header appropriate for the filename.
 119   * non-ascii filenames are urlencoded and a filename* parameter is added
 120   *
 121   * @param {String} filename
 122   * @return {String}
 123   * @api private
 124   */
 125  
 126  exports.contentDisposition = deprecate.function(contentDisposition,
 127    'utils.contentDisposition: use content-disposition npm module instead');
 128  
 129  /**
 130   * Parse accept params `str` returning an
 131   * object with `.value`, `.quality` and `.params`.
 132   * also includes `.originalIndex` for stable sorting
 133   *
 134   * @param {String} str
 135   * @return {Object}
 136   * @api private
 137   */
 138  
 139  function acceptParams(str, index) {
 140    var parts = str.split(/ *; */);
 141    var ret = { value: parts[0], quality: 1, params: {}, originalIndex: index };
 142  
 143    for (var i = 1; i < parts.length; ++i) {
 144      var pms = parts[i].split(/ *= */);
 145      if ('q' === pms[0]) {
 146        ret.quality = parseFloat(pms[1]);
 147      } else {
 148        ret.params[pms[0]] = pms[1];
 149      }
 150    }
 151  
 152    return ret;
 153  }
 154  
 155  /**
 156   * Compile "etag" value to function.
 157   *
 158   * @param  {Boolean|String|Function} val
 159   * @return {Function}
 160   * @api private
 161   */
 162  
 163  exports.compileETag = function(val) {
 164    var fn;
 165  
 166    if (typeof val === 'function') {
 167      return val;
 168    }
 169  
 170    switch (val) {
 171      case true:
 172        fn = exports.wetag;
 173        break;
 174      case false:
 175        break;
 176      case 'strong':
 177        fn = exports.etag;
 178        break;
 179      case 'weak':
 180        fn = exports.wetag;
 181        break;
 182      default:
 183        throw new TypeError('unknown value for etag function: ' + val);
 184    }
 185  
 186    return fn;
 187  }
 188  
 189  /**
 190   * Compile "query parser" value to function.
 191   *
 192   * @param  {String|Function} val
 193   * @return {Function}
 194   * @api private
 195   */
 196  
 197  exports.compileQueryParser = function compileQueryParser(val) {
 198    var fn;
 199  
 200    if (typeof val === 'function') {
 201      return val;
 202    }
 203  
 204    switch (val) {
 205      case true:
 206        fn = querystring.parse;
 207        break;
 208      case false:
 209        fn = newObject;
 210        break;
 211      case 'extended':
 212        fn = parseExtendedQueryString;
 213        break;
 214      case 'simple':
 215        fn = querystring.parse;
 216        break;
 217      default:
 218        throw new TypeError('unknown value for query parser function: ' + val);
 219    }
 220  
 221    return fn;
 222  }
 223  
 224  /**
 225   * Compile "proxy trust" value to function.
 226   *
 227   * @param  {Boolean|String|Number|Array|Function} val
 228   * @return {Function}
 229   * @api private
 230   */
 231  
 232  exports.compileTrust = function(val) {
 233    if (typeof val === 'function') return val;
 234  
 235    if (val === true) {
 236      // Support plain true/false
 237      return function(){ return true };
 238    }
 239  
 240    if (typeof val === 'number') {
 241      // Support trusting hop count
 242      return function(a, i){ return i < val };
 243    }
 244  
 245    if (typeof val === 'string') {
 246      // Support comma-separated values
 247      val = val.split(/ *, */);
 248    }
 249  
 250    return proxyaddr.compile(val || []);
 251  }
 252  
 253  /**
 254   * Set the charset in a given Content-Type string.
 255   *
 256   * @param {String} type
 257   * @param {String} charset
 258   * @return {String}
 259   * @api private
 260   */
 261  
 262  exports.setCharset = function setCharset(type, charset) {
 263    if (!type || !charset) {
 264      return type;
 265    }
 266  
 267    // parse type
 268    var parsed = contentType.parse(type);
 269  
 270    // set charset
 271    parsed.parameters.charset = charset;
 272  
 273    // format type
 274    return contentType.format(parsed);
 275  };
 276  
 277  /**
 278   * Parse an extended query string with qs.
 279   *
 280   * @return {Object}
 281   * @private
 282   */
 283  
 284  function parseExtendedQueryString(str) {
 285    return qs.parse(str, {
 286      allowPrototypes: true
 287    });
 288  }
 289  
 290  /**
 291   * Return new empty object.
 292   *
 293   * @return {Object}
 294   * @api private
 295   */
 296  
 297  function newObject() {
 298    return {};
 299  }
 300  
```

## 4. Status

- `Survived`: at least one test ran the mutated code, and no test failed.
- `NoCoverage`: no test ran the mutated code.

## 5. Survivors (58)

### Mutant 1

- Status: NoCoverage
- Location: line 35:42 to line 41:2
- Mutator: BlockStatement
- Original code:

```js
{
  var buf = !Buffer.isBuffer(body)
    ? new Buffer(body, encoding)
    : body;

  return etag(buf, {weak: false});
}
```

- Replacement:

```js
{}
```

### Mutant 2

- Status: NoCoverage
- Location: line 36:13 to line 36:35
- Mutator: BooleanLiteral
- Original code:

```js
!Buffer.isBuffer(body)
```

- Replacement:

```js
Buffer.isBuffer(body)
```

### Mutant 3

- Status: NoCoverage
- Location: line 40:20 to line 40:33
- Mutator: ObjectLiteral
- Original code:

```js
{weak: false}
```

- Replacement:

```js
{}
```

### Mutant 4

- Status: NoCoverage
- Location: line 40:27 to line 40:32
- Mutator: BooleanLiteral
- Original code:

```js
false
```

- Replacement:

```js
true
```

### Mutant 6

- Status: Survived
- Location: line 53:13 to line 53:35
- Mutator: BooleanLiteral
- Original code:

```js
!Buffer.isBuffer(body)
```

- Replacement:

```js
Buffer.isBuffer(body)
```

### Mutant 17

- Status: Survived
- Location: line 70:7 to line 70:42
- Mutator: LogicalOperator
- Original code:

```js
':' === path[1] && '\\' === path[2]
```

- Replacement:

```js
':' === path[1] || '\\' === path[2]
```

### Mutant 18

- Status: Survived
- Location: line 70:7 to line 70:22
- Mutator: ConditionalExpression
- Original code:

```js
':' === path[1]
```

- Replacement:

```js
true
```

### Mutant 21

- Status: Survived
- Location: line 70:26 to line 70:42
- Mutator: ConditionalExpression
- Original code:

```js
'\\' === path[2]
```

- Replacement:

```js
true
```

### Mutant 26

- Status: Survived
- Location: line 71:7 to line 71:38
- Mutator: ConditionalExpression
- Original code:

```js
'\\\\' === path.substring(0, 2)
```

- Replacement:

```js
false
```

### Mutant 28

- Status: Survived
- Location: line 71:7 to line 71:13
- Mutator: StringLiteral
- Original code:

```js
'\\\\'
```

- Replacement:

```js
""
```

### Mutant 29

- Status: Survived
- Location: line 71:18 to line 71:38
- Mutator: MethodExpression
- Original code:

```js
path.substring(0, 2)
```

- Replacement:

```js
path
```

### Mutant 30

- Status: NoCoverage
- Location: line 71:47 to line 71:51
- Mutator: BooleanLiteral
- Original code:

```js
true
```

- Replacement:

```js
false
```

### Mutant 31

- Status: Survived
- Location: line 83:3 to line 83:56
- Mutator: StringLiteral
- Original code:

```js
'utils.flatten: use array-flatten npm module instead'
```

- Replacement:

```js
""
```

### Mutant 44

- Status: Survived
- Location: line 127:3 to line 127:73
- Mutator: StringLiteral
- Original code:

```js
'utils.contentDisposition: use content-disposition npm module instead'
```

- Replacement:

```js
""
```

### Mutant 47

- Status: Survived
- Location: line 140:25 to line 140:32
- Mutator: Regex
- Original code:

```js
/ *; */
```

- Replacement:

```js
/ *; /
```

### Mutant 49

- Status: Survived
- Location: line 143:19 to line 143:35
- Mutator: ConditionalExpression
- Original code:

```js
i < parts.length
```

- Replacement:

```js
false
```

### Mutant 51

- Status: Survived
- Location: line 143:19 to line 143:35
- Mutator: EqualityOperator
- Original code:

```js
i < parts.length
```

- Replacement:

```js
i >= parts.length
```

### Mutant 53

- Status: Survived
- Location: line 143:42 to line 150:4
- Mutator: BlockStatement
- Original code:

```js
{
    var pms = parts[i].split(/ *= */);
    if ('q' === pms[0]) {
      ret.quality = parseFloat(pms[1]);
    } else {
      ret.params[pms[0]] = pms[1];
    }
  }
```

- Replacement:

```js
{}
```

### Mutant 54

- Status: Survived
- Location: line 144:30 to line 144:37
- Mutator: Regex
- Original code:

```js
/ *= */
```

- Replacement:

```js
/ = */
```

### Mutant 55

- Status: Survived
- Location: line 144:30 to line 144:37
- Mutator: Regex
- Original code:

```js
/ *= */
```

- Replacement:

```js
/ *= /
```

### Mutant 56

- Status: Survived
- Location: line 145:9 to line 145:23
- Mutator: ConditionalExpression
- Original code:

```js
'q' === pms[0]
```

- Replacement:

```js
true
```

### Mutant 57

- Status: Survived
- Location: line 145:9 to line 145:23
- Mutator: ConditionalExpression
- Original code:

```js
'q' === pms[0]
```

- Replacement:

```js
false
```

### Mutant 58

- Status: Survived
- Location: line 145:9 to line 145:23
- Mutator: EqualityOperator
- Original code:

```js
'q' === pms[0]
```

- Replacement:

```js
'q' !== pms[0]
```

### Mutant 59

- Status: Survived
- Location: line 145:9 to line 145:12
- Mutator: StringLiteral
- Original code:

```js
'q'
```

- Replacement:

```js
""
```

### Mutant 60

- Status: Survived
- Location: line 145:25 to line 147:6
- Mutator: BlockStatement
- Original code:

```js
{
      ret.quality = parseFloat(pms[1]);
    }
```

- Replacement:

```js
{}
```

### Mutant 61

- Status: NoCoverage
- Location: line 147:12 to line 149:6
- Mutator: BlockStatement
- Original code:

```js
{
      ret.params[pms[0]] = pms[1];
    }
```

- Replacement:

```js
{}
```

### Mutant 64

- Status: Survived
- Location: line 166:7 to line 166:32
- Mutator: ConditionalExpression
- Original code:

```js
typeof val === 'function'
```

- Replacement:

```js
false
```

### Mutant 66

- Status: Survived
- Location: line 166:22 to line 166:32
- Mutator: StringLiteral
- Original code:

```js
'function'
```

- Replacement:

```js
""
```

### Mutant 67

- Status: NoCoverage
- Location: line 166:34 to line 168:4
- Mutator: BlockStatement
- Original code:

```js
{
    return val;
  }
```

- Replacement:

```js
{}
```

### Mutant 72

- Status: NoCoverage
- Location: line 176:5 to line 178:13
- Mutator: ConditionalExpression
- Original code:

```js
case 'strong':
      fn = exports.etag;
      break;
```

- Replacement:

```js
case 'strong':
```

### Mutant 73

- Status: Survived
- Location: line 176:10 to line 176:18
- Mutator: StringLiteral
- Original code:

```js
'strong'
```

- Replacement:

```js
""
```

### Mutant 78

- Status: Survived
- Location: line 183:27 to line 183:62
- Mutator: StringLiteral
- Original code:

```js
'unknown value for etag function: '
```

- Replacement:

```js
""
```

### Mutant 79

- Status: NoCoverage
- Location: line 197:63 to line 222:2
- Mutator: BlockStatement
- Original code:

```js
{
  var fn;

  if (typeof val === 'function') {
    return val;
  }

  switch (val) {
    case true:
      fn = querystring.parse;
      break;
    case false:
      fn = newObject;
      break;
    case 'extended':
      fn = parseExtendedQueryString;
      break;
    case 'simple':
      fn = querystring.parse;
      break;
    default:
      throw new TypeError('unknown value for query parser function: ' + val);
  }

  return fn;
}
```

- Replacement:

```js
{}
```

### Mutant 80

- Status: NoCoverage
- Location: line 200:7 to line 200:32
- Mutator: ConditionalExpression
- Original code:

```js
typeof val === 'function'
```

- Replacement:

```js
true
```

### Mutant 81

- Status: NoCoverage
- Location: line 200:7 to line 200:32
- Mutator: ConditionalExpression
- Original code:

```js
typeof val === 'function'
```

- Replacement:

```js
false
```

### Mutant 82

- Status: NoCoverage
- Location: line 200:7 to line 200:32
- Mutator: EqualityOperator
- Original code:

```js
typeof val === 'function'
```

- Replacement:

```js
typeof val !== 'function'
```

### Mutant 83

- Status: NoCoverage
- Location: line 200:22 to line 200:32
- Mutator: StringLiteral
- Original code:

```js
'function'
```

- Replacement:

```js
""
```

### Mutant 84

- Status: NoCoverage
- Location: line 200:34 to line 202:4
- Mutator: BlockStatement
- Original code:

```js
{
    return val;
  }
```

- Replacement:

```js
{}
```

### Mutant 85

- Status: NoCoverage
- Location: line 205:5 to line 207:13
- Mutator: ConditionalExpression
- Original code:

```js
case true:
      fn = querystring.parse;
      break;
```

- Replacement:

```js
case true:
```

### Mutant 86

- Status: NoCoverage
- Location: line 205:10 to line 205:14
- Mutator: BooleanLiteral
- Original code:

```js
true
```

- Replacement:

```js
false
```

### Mutant 87

- Status: NoCoverage
- Location: line 208:5 to line 210:13
- Mutator: ConditionalExpression
- Original code:

```js
case false:
      fn = newObject;
      break;
```

- Replacement:

```js
case false:
```

### Mutant 88

- Status: NoCoverage
- Location: line 208:10 to line 208:15
- Mutator: BooleanLiteral
- Original code:

```js
false
```

- Replacement:

```js
true
```

### Mutant 89

- Status: NoCoverage
- Location: line 211:5 to line 213:13
- Mutator: ConditionalExpression
- Original code:

```js
case 'extended':
      fn = parseExtendedQueryString;
      break;
```

- Replacement:

```js
case 'extended':
```

### Mutant 90

- Status: NoCoverage
- Location: line 211:10 to line 211:20
- Mutator: StringLiteral
- Original code:

```js
'extended'
```

- Replacement:

```js
""
```

### Mutant 91

- Status: NoCoverage
- Location: line 214:5 to line 216:13
- Mutator: ConditionalExpression
- Original code:

```js
case 'simple':
      fn = querystring.parse;
      break;
```

- Replacement:

```js
case 'simple':
```

### Mutant 92

- Status: NoCoverage
- Location: line 214:10 to line 214:18
- Mutator: StringLiteral
- Original code:

```js
'simple'
```

- Replacement:

```js
""
```

### Mutant 93

- Status: NoCoverage
- Location: line 217:5 to line 218:78
- Mutator: ConditionalExpression
- Original code:

```js
default:
      throw new TypeError('unknown value for query parser function: ' + val);
```

- Replacement:

```js
default:
```

### Mutant 95

- Status: NoCoverage
- Location: line 218:27 to line 218:70
- Mutator: StringLiteral
- Original code:

```js
'unknown value for query parser function: '
```

- Replacement:

```js
""
```

### Mutant 98

- Status: Survived
- Location: line 233:7 to line 233:32
- Mutator: ConditionalExpression
- Original code:

```js
typeof val === 'function'
```

- Replacement:

```js
false
```

### Mutant 100

- Status: Survived
- Location: line 233:22 to line 233:32
- Mutator: StringLiteral
- Original code:

```js
'function'
```

- Replacement:

```js
""
```

### Mutant 116

- Status: Survived
- Location: line 242:35 to line 242:42
- Mutator: EqualityOperator
- Original code:

```js
i < val
```

- Replacement:

```js
i <= val
```

### Mutant 118

- Status: Survived
- Location: line 245:7 to line 245:30
- Mutator: ConditionalExpression
- Original code:

```js
typeof val === 'string'
```

- Replacement:

```js
true
```

### Mutant 124

- Status: Survived
- Location: line 247:21 to line 247:28
- Mutator: Regex
- Original code:

```js
/ *, */
```

- Replacement:

```js
/ *, /
```

### Mutant 128

- Status: NoCoverage
- Location: line 250:35 to line 250:37
- Mutator: ArrayDeclaration
- Original code:

```js
[]
```

- Replacement:

```js
["Stryker was here"]
```

### Mutant 136

- Status: NoCoverage
- Location: line 284:40 to line 288:2
- Mutator: BlockStatement
- Original code:

```js
{
  return qs.parse(str, {
    allowPrototypes: true
  });
}
```

- Replacement:

```js
{}
```

### Mutant 137

- Status: NoCoverage
- Location: line 285:24 to line 287:4
- Mutator: ObjectLiteral
- Original code:

```js
{
    allowPrototypes: true
  }
```

- Replacement:

```js
{}
```

### Mutant 138

- Status: NoCoverage
- Location: line 286:22 to line 286:26
- Mutator: BooleanLiteral
- Original code:

```js
true
```

- Replacement:

```js
false
```

### Mutant 139

- Status: NoCoverage
- Location: line 297:22 to line 299:2
- Mutator: BlockStatement
- Original code:

```js
{
  return {};
}
```

- Replacement:

```js
{}
```

