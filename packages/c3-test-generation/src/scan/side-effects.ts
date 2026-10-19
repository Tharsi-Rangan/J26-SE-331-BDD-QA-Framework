// C3-04 side-effect guess for each scanned dependency (FR2 checklist: "Side-effect guess").
// Values are the `dependency.side_effect` enum of c3-mock-decisions.schema.json.
// It is a GUESS from known names; C3-05 rules use it and the reason text says where it came from.

export type SideEffect = 'io' | 'network' | 'time' | 'random' | 'database' | 'none' | 'unknown';

export interface SideEffectGuess {
  sideEffect: SideEffect;
  basis: string; // why, in a few words, e.g. "node builtin 'fs'"
}

/** Node.js built-in modules. A symbol entry wins over the module entry (crypto.createHash is pure). */
const BUILTIN: Record<string, SideEffect> = {
  fs: 'io',
  'fs/promises': 'io',
  child_process: 'io',
  readline: 'io',
  stream: 'io',
  tty: 'io',
  os: 'io',
  process: 'io',
  worker_threads: 'io',
  cluster: 'io',
  http: 'network',
  https: 'network',
  http2: 'network',
  net: 'network',
  tls: 'network',
  dgram: 'network',
  dns: 'network',
  timers: 'time',
  'timers/promises': 'time',
  perf_hooks: 'time',
  path: 'none',
  url: 'none',
  util: 'none',
  querystring: 'none',
  events: 'none',
  buffer: 'none',
  string_decoder: 'none',
  assert: 'none',
  zlib: 'none',
  crypto: 'none',
};
const BUILTIN_SYMBOL: Record<string, SideEffect> = {
  'crypto#randomBytes': 'random',
  'crypto#randomUUID': 'random',
  'crypto#randomInt': 'random',
  'crypto#randomFillSync': 'random',
  'crypto#getRandomValues': 'random',
};

/** Globals reported by the scanner (Math only reports `random`). */
const GLOBAL: Record<string, SideEffect> = {
  Date: 'time',
  Math: 'random',
  process: 'io',
  console: 'io',
  setTimeout: 'time',
  setInterval: 'time',
  setImmediate: 'time',
  clearTimeout: 'time',
  clearInterval: 'time',
  queueMicrotask: 'time',
  performance: 'time',
  fetch: 'network',
  crypto: 'random',
};

/** Well-known npm packages. Anything else is 'unknown'. */
const PACKAGE: Record<string, SideEffect> = {
  // databases
  mongoose: 'database',
  mongodb: 'database',
  pg: 'database',
  mysql: 'database',
  mysql2: 'database',
  sqlite3: 'database',
  'better-sqlite3': 'database',
  redis: 'database',
  ioredis: 'database',
  sequelize: 'database',
  knex: 'database',
  typeorm: 'database',
  '@prisma/client': 'database',
  // network
  axios: 'network',
  'node-fetch': 'network',
  got: 'network',
  request: 'network',
  superagent: 'network',
  ws: 'network',
  'socket.io': 'network',
  nodemailer: 'network',
  // random / time
  uuid: 'random',
  nanoid: 'random',
  // files and processes
  'fs-extra': 'io',
  glob: 'io',
  mkdirp: 'io',
  rimraf: 'io',
  chokidar: 'io',
  'graceful-fs': 'io',
  // logging (output only)
  debug: 'io',
  depd: 'io',
  winston: 'io',
  pino: 'io',
  // pure helpers seen in the BugsJS pilots and common utilities
  'array-flatten': 'none',
  'content-disposition': 'none',
  'content-type': 'none',
  etag: 'none',
  'proxy-addr': 'none',
  qs: 'none',
  mime: 'none',
  'mime-types': 'none',
  dot: 'none',
  svgo: 'none',
  long: 'none',
  lodash: 'none',
  underscore: 'none',
  'is-type-of': 'none',
  utility: 'none',
};
/** Package symbols that differ from the package entry (send.mime is a lookup table). */
const PACKAGE_SYMBOL: Record<string, SideEffect> = {
  'send#mime': 'none',
};

/** Logging dependencies: they only write output, so C3-05 never needs to mock them. */
export const LOGGING = new Set(['console', 'debug', 'depd', 'winston', 'pino']);

/** Words in internal file names that usually mean database / network access. */
const INTERNAL_WORDS: [ReadonlySet<string>, SideEffect][] = [
  [
    new Set([
      'repo',
      'repository',
      'repositories',
      'dao',
      'db',
      'database',
      'store',
      'model',
      'models',
    ]),
    'database',
  ],
  [new Set(['api', 'client', 'http', 'fetcher', 'gateway']), 'network'],
];

/** 'src/userRepository.js' -> ['src', 'user', 'repository'] (splits folders, -, _, . and camelCase). */
export function pathWords(p: string): string[] {
  return p
    .replace(/\.[cm]?[jt]s$/, '')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .split(/[\/_.\s-]+/)
    .filter(Boolean)
    .map((w) => w.toLowerCase());
}

/** Package name of a bare specifier: '@scope/pkg/sub' -> '@scope/pkg', 'lodash/merge' -> 'lodash'. */
export function packageName(spec: string): string {
  const parts = spec.split('/');
  return spec.startsWith('@') ? parts.slice(0, 2).join('/') : parts[0]!;
}

export function guessExternalOrBuiltin(
  kind: 'node_builtin' | 'external_package' | 'global_object',
  spec: string,
  symbol: string,
): SideEffectGuess {
  if (kind === 'global_object') {
    const s = GLOBAL[spec];
    return s
      ? { sideEffect: s, basis: `global '${spec}'` }
      : { sideEffect: 'unknown', basis: `global '${spec}'` };
  }
  if (kind === 'node_builtin') {
    const mod = spec.replace(/^node:/, '');
    const s = BUILTIN_SYMBOL[`${mod}#${symbol}`] ?? BUILTIN[mod] ?? BUILTIN[mod.split('/')[0]!];
    return s
      ? { sideEffect: s, basis: `node builtin '${mod}'` }
      : { sideEffect: 'unknown', basis: `node builtin '${mod}' not in the table` };
  }
  const pkg = packageName(spec);
  const s = PACKAGE_SYMBOL[`${pkg}#${symbol}`] ?? PACKAGE[pkg];
  return s
    ? { sideEffect: s, basis: `known package '${pkg}'` }
    : { sideEffect: 'unknown', basis: `package '${pkg}' not in the table` };
}

/** Internal module: JSON is data; a telling file name wins; else the worst effect of what it uses. */
export function guessInternal(
  resolvedPath: string | undefined,
  innerEffects: SideEffect[],
): SideEffectGuess {
  if (!resolvedPath)
    return { sideEffect: 'unknown', basis: 'internal module could not be resolved' };
  if (resolvedPath.endsWith('.json')) return { sideEffect: 'none', basis: 'JSON data file' };
  const words = pathWords(resolvedPath);
  for (const [names, s] of INTERNAL_WORDS) {
    const hit = words.find((w) => names.has(w));
    if (hit) return { sideEffect: s, basis: `file name '${resolvedPath}' contains '${hit}'` };
  }
  const worst = worstOf(innerEffects);
  return {
    sideEffect: worst,
    basis: innerEffects.length
      ? `what it reaches in '${resolvedPath}' when called`
      : `'${resolvedPath}' uses no risky dependency`,
  };
}

/** Most important effect first: a dependency that touches a database matters more than one that logs. */
const ORDER: SideEffect[] = ['database', 'network', 'io', 'time', 'random', 'unknown', 'none'];
export function worstOf(effects: SideEffect[]): SideEffect {
  for (const s of ORDER) if (effects.includes(s)) return s;
  return 'none';
}
