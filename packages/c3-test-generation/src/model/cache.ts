// C3-06 answer cache: every real model answer is saved, keyed by the request.
// Re-runs are free and repeatable, and the PP1 demo works offline with LLM_CACHE=readonly.
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import type { CacheMode } from './config.js';
import {
  ModelCacheMiss,
  type ModelClient,
  type ModelRequest,
  type ModelResponse,
} from './types.js';

export interface CachedAnswer {
  key: string;
  model_tag: string;
  purpose?: string;
  request: Omit<ModelRequest, 'purpose'>;
  text: string;
  recorded_at: string;
  latency_ms: number;
}

/** Same model + same messages + same settings -> same key (purpose is only a label). */
export function cacheKey(modelTag: string, request: ModelRequest): string {
  const { purpose: _ignored, ...rest } = request;
  const canonical = JSON.stringify({
    modelTag,
    messages: rest.messages,
    temperature: rest.temperature ?? 0,
    maxTokens: rest.maxTokens ?? null,
    json: rest.json ?? false,
  });
  return crypto.createHash('sha256').update(canonical).digest('hex');
}

export class CachedModelClient implements ModelClient {
  readonly modelTag: string;
  hits = 0;
  misses = 0;

  constructor(
    private readonly inner: ModelClient,
    private readonly dir: string,
    private readonly mode: CacheMode = 'readwrite',
  ) {
    this.modelTag = inner.modelTag;
  }

  private file(key: string): string {
    return path.join(this.dir, key.slice(0, 2), `${key}.json`);
  }

  async complete(request: ModelRequest): Promise<ModelResponse> {
    if (this.mode === 'off') return this.inner.complete(request);
    const key = cacheKey(this.modelTag, request);
    const file = this.file(key);
    if (fs.existsSync(file)) {
      const saved = JSON.parse(fs.readFileSync(file, 'utf8')) as CachedAnswer;
      this.hits++;
      const [model, provider] = splitTag(saved.model_tag);
      return { text: saved.text, model, provider, cached: true, latencyMs: 0 };
    }
    this.misses++;
    if (this.mode === 'readonly') throw new ModelCacheMiss(key, request.purpose);
    const res = await this.inner.complete(request);
    const { purpose, ...stored } = request;
    const entry: CachedAnswer = {
      key,
      model_tag: this.modelTag,
      ...(purpose ? { purpose } : {}),
      request: stored,
      text: res.text,
      recorded_at: new Date().toISOString(),
      latency_ms: res.latencyMs,
    };
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, JSON.stringify(entry, null, 2) + '\n');
    return res;
  }
}

function splitTag(tag: string): [string, string] {
  const at = tag.lastIndexOf('@');
  return at < 0 ? [tag, 'unknown'] : [tag.slice(0, at), tag.slice(at + 1)];
}
