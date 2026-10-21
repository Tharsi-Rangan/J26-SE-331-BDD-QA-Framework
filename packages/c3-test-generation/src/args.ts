import path from 'node:path';
import { parseArgs } from 'node:util';

/** Options every component CLI accepts (docs/INTEGRATION_RULES.md section 4). */
export interface RunOptions {
  in?: string;
  out: string;
  srs?: string;
  subjectRoot?: string;
  /** --no-model: never call a model; rule defaults are used (also the default when .env has no model). */
  noModel?: boolean;
  /** --open: open the HTML report (c3/c3_report.html) in the browser at the end (C3-16). */
  open?: boolean;
}

/**
 * Parse `c3 run --in runs/<RUN-ID> --subject-root <path> --out runs/<RUN-ID>`.
 * Throws an Error with a readable message when the command line is wrong.
 */
export function parseRunArgs(argv: string[], baseDir = callerDir()): RunOptions {
  const { positionals, values } = parseArgs({
    args: argv,
    allowPositionals: true,
    options: {
      in: { type: 'string' },
      out: { type: 'string' },
      srs: { type: 'string' },
      'subject-root': { type: 'string' },
      'no-model': { type: 'boolean' },
      open: { type: 'boolean' },
    },
  });
  if (positionals[0] !== 'run') {
    throw new Error('Usage: c3 run --in runs/<RUN-ID> --subject-root <path> --out runs/<RUN-ID>');
  }
  if (!values.out) {
    throw new Error('Missing --out <run folder>');
  }
  const abs = (p?: string) => (p === undefined ? undefined : path.resolve(baseDir, p));
  return {
    in: abs(values.in),
    out: path.resolve(baseDir, values.out),
    srs: abs(values.srs),
    subjectRoot: abs(values['subject-root']),
    ...(values['no-model'] ? { noModel: true } : {}),
    ...(values.open ? { open: true } : {}),
  };
}

/** Options for `c3 scan` (C3-04): scan one subject module and print or save the result. */
export interface ScanCommandOptions {
  subjectRoot: string;
  module: string;
  exports: string[];
  out?: string;
}

/**
 * Parse `c3 scan --subject-root <path> --module lib/utils.js [--exports a,b] [--out scan.json]`.
 */
export function parseScanArgs(argv: string[], baseDir = callerDir()): ScanCommandOptions {
  const { positionals, values } = parseArgs({
    args: argv,
    allowPositionals: true,
    options: {
      'subject-root': { type: 'string' },
      module: { type: 'string' },
      exports: { type: 'string' },
      out: { type: 'string' },
    },
  });
  const usage =
    'Usage: c3 scan --subject-root <path> --module <path inside subject> [--exports a,b] [--out file.json]';
  if (positionals[0] !== 'scan' || !values['subject-root'] || !values.module) {
    throw new Error(usage);
  }
  return {
    subjectRoot: path.resolve(baseDir, values['subject-root']),
    module: values.module,
    exports: values.exports
      ? values.exports
          .split(',')
          .map((e) => e.trim())
          .filter(Boolean)
      : [],
    out: values.out === undefined ? undefined : path.resolve(baseDir, values.out),
  };
}

export interface PilotCommandOptions {
  run: string;
  buggy: string;
  fixed: string;
  label?: string;
  open?: boolean;
}

/** Parse `c3 pilot --run runs/<RUN-ID> --buggy <subject root> --fixed <subject root> [--label Express-5]`. */
export function parsePilotArgs(argv: string[], baseDir = callerDir()): PilotCommandOptions {
  const { positionals, values } = parseArgs({
    args: argv,
    allowPositionals: true,
    options: {
      run: { type: 'string' },
      buggy: { type: 'string' },
      fixed: { type: 'string' },
      label: { type: 'string' },
      open: { type: 'boolean' },
    },
  });
  if (positionals[0] !== 'pilot' || !values.run || !values.buggy || !values.fixed) {
    throw new Error(
      'Usage: c3 pilot --run runs/<RUN-ID> --buggy <subject root> --fixed <subject root> [--label <name>] [--open]',
    );
  }
  return {
    run: path.resolve(baseDir, values.run),
    buggy: path.resolve(baseDir, values.buggy),
    fixed: path.resolve(baseDir, values.fixed),
    ...(values.label ? { label: values.label } : {}),
    ...(values.open ? { open: true } : {}),
  };
}

/** Options for `c3 report` (C3-16). */
export interface ReportCommandOptions {
  /** One run folder: write <run>/c3/c3_report.html. */
  run?: string;
  /** A folder of runs: write every run page and <dir>/c3_batch_report.html. */
  index?: string;
  /** --runs a,b: only these run folders (names inside --index), in this order. */
  runs?: string[];
  title?: string;
  open?: boolean;
}

/** Parse `c3 report --run runs/<RUN-ID> [--open]` or `c3 report --index runs [--runs a,b] [--open]`. */
export function parseReportArgs(argv: string[], baseDir = callerDir()): ReportCommandOptions {
  const { positionals, values } = parseArgs({
    args: argv,
    allowPositionals: true,
    options: {
      run: { type: 'string' },
      index: { type: 'string' },
      runs: { type: 'string' },
      title: { type: 'string' },
      open: { type: 'boolean' },
    },
  });
  if (positionals[0] !== 'report' || !values.run === !values.index) {
    throw new Error(
      'Usage: c3 report --run runs/<RUN-ID> [--open]   or   c3 report --index runs [--runs a,b] [--title <text>] [--open]',
    );
  }
  const runs = values.runs
    ?.split(',')
    .map((r) => r.trim())
    .filter(Boolean);
  return {
    ...(values.run ? { run: path.resolve(baseDir, values.run) } : {}),
    ...(values.index ? { index: path.resolve(baseDir, values.index) } : {}),
    ...(runs?.length ? { runs } : {}),
    ...(values.title ? { title: values.title } : {}),
    ...(values.open ? { open: true } : {}),
  };
}

/**
 * Folder the user ran the command from. pnpm runs scripts inside the package folder,
 * but sets INIT_CWD to the original folder, so relative paths work from the repo root.
 */
export function callerDir(): string {
  return process.env.INIT_CWD ?? process.cwd();
}
