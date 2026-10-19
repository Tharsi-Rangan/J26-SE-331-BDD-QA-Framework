import path from 'node:path';
import { parseArgs } from 'node:util';
import { TRACE_SIGNAL_MODES, type TraceSignalMode } from './signal.js';

/** Options every component CLI accepts (docs/INTEGRATION_RULES.md section 4). */
export interface RunOptions {
  in?: string;
  out: string;
  srs?: string;
  subjectRoot?: string;
  traceSignal: TraceSignalMode;
}

/**
 * Parse `c4 run --in runs/<RUN-ID> --subject-root <path> --out runs/<RUN-ID> [--trace-signal <mode>]`.
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
      'trace-signal': { type: 'string', default: 'coverage_only' },
    },
  });
  if (positionals[0] !== 'run') {
    throw new Error('Usage: c4 run --in runs/<RUN-ID> --subject-root <path> --out runs/<RUN-ID>');
  }
  if (!values.out) {
    throw new Error('Missing --out <run folder>');
  }
  const traceSignal = values['trace-signal'] as TraceSignalMode;
  if (!TRACE_SIGNAL_MODES.includes(traceSignal)) {
    throw new Error(`--trace-signal must be one of: ${TRACE_SIGNAL_MODES.join(', ')}`);
  }
  const abs = (p?: string) => (p === undefined ? undefined : path.resolve(baseDir, p));
  return {
    in: abs(values.in),
    out: path.resolve(baseDir, values.out),
    srs: abs(values.srs),
    subjectRoot: abs(values['subject-root']),
    traceSignal,
  };
}

/**
 * Folder the user ran the command from. pnpm runs scripts inside the package folder,
 * but sets INIT_CWD to the original folder, so relative paths work from the repo root.
 */
export function callerDir(): string {
  return process.env.INIT_CWD ?? process.cwd();
}
