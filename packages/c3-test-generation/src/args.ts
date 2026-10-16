import path from 'node:path';
import { parseArgs } from 'node:util';

/** Options every component CLI accepts (docs/INTEGRATION_RULES.md section 4). */
export interface RunOptions {
  in?: string;
  out: string;
  srs?: string;
  subjectRoot?: string;
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

/**
 * Folder the user ran the command from. pnpm runs scripts inside the package folder,
 * but sets INIT_CWD to the original folder, so relative paths work from the repo root.
 */
export function callerDir(): string {
  return process.env.INIT_CWD ?? process.cwd();
}
