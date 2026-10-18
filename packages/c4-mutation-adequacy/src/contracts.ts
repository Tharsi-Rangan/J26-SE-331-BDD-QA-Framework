import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { Ajv2020 } from 'ajv/dist/2020.js';
import addFormatsModule from 'ajv-formats';

// ajv-formats is CommonJS; under NodeNext its default export is the module object.
const addFormats = addFormatsModule as unknown as (ajv: Ajv2020) => Ajv2020;

const require = createRequire(import.meta.url);

/** Folder with the shared JSON Schemas of @j26/contracts. */
export const schemaDir = path.join(
  path.dirname(require.resolve('@j26/contracts/package.json')),
  'schemas',
);

let ajv: Ajv2020 | undefined;

function getAjv(): Ajv2020 {
  if (ajv) return ajv;
  ajv = new Ajv2020({ allErrors: true, strict: false });
  addFormats(ajv);
  for (const f of fs.readdirSync(schemaDir).filter((n) => n.endsWith('.schema.json'))) {
    ajv.addSchema(JSON.parse(fs.readFileSync(path.join(schemaDir, f), 'utf8')), f);
  }
  return ajv;
}

/** Throw an Error that lists every schema problem when `data` does not match `schema`. */
export function assertMatchesSchema(data: unknown, schema: string, label: string): void {
  const validate = getAjv().getSchema(schema);
  if (!validate) throw new Error(`Unknown schema ${schema}`);
  if (!validate(data)) {
    const errors = (validate.errors ?? []).map((e) => `  ${e.instancePath || '/'} ${e.message}`);
    throw new Error(`${label} does not match ${schema}:\n${errors.join('\n')}`);
  }
}
