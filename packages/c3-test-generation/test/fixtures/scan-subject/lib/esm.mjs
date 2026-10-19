import fs from 'node:fs';
import * as qs from 'qs';
import { setTimeout as wait } from 'node:timers/promises';

export function readCount(file) {
  return qs.parse(fs.readFileSync(file, 'utf8')).count;
}

export async function later(ms) {
  await wait(ms);
  return 'done';
}
