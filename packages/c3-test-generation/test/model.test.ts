import fs from 'node:fs';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { afterAll, afterEach, beforeAll, describe, expect, test } from 'vitest';
import {
  CachedModelClient,
  cacheKey,
  createModelClient,
  FakeModelClient,
  ModelCacheMiss,
  ModelError,
  OpenAICompatibleClient,
  parseJsonAnswer,
  providerOf,
  readModelConfig,
  type ModelConfig,
} from '../src/model/index.js';

// ---- a tiny OpenAI-compatible server (stands in for Ollama / Hugging Face) ----
interface Seen {
  auth?: string;
  body: any;
}
let server: http.Server;
let baseUrl = '';
const seen: Seen[] = [];
let plan: ((n: number) => { status: number; body?: unknown; delayMs?: number }) | undefined;

beforeAll(async () => {
  server = http.createServer((req, res) => {
    let raw = '';
    req.on('data', (c) => (raw += c));
    req.on('end', () => {
      const n = seen.length;
      seen.push({ auth: req.headers.authorization, body: JSON.parse(raw || '{}') });
      const step = plan?.(n) ?? {
        status: 200,
        body: {
          model: 'm',
          choices: [{ message: { content: `answer ${n + 1}` } }],
          usage: { prompt_tokens: 7, completion_tokens: 2 },
        },
      };
      setTimeout(() => {
        if (res.destroyed) return;
        res.writeHead(step.status, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(step.body ?? { error: 'boom' }));
      }, step.delayMs ?? 0);
    });
  });
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', r));
  baseUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}/v1`;
});
afterAll(() => new Promise<void>((r) => server.close(() => r())));

const dirs: string[] = [];
afterEach(() => {
  seen.length = 0;
  plan = undefined;
  for (const d of dirs.splice(0)) fs.rmSync(d, { recursive: true, force: true });
});
const tmp = () => {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), 'c3-model-'));
  dirs.push(d);
  return d;
};
const noWait = { sleep: async () => {} };
const cfg = (over: Partial<ModelConfig> = {}): ModelConfig => ({
  baseUrl,
  model: 'qwen2.5-coder:3b',
  provider: 'ollama',
  timeoutMs: 2000,
  maxRetries: 2,
  cacheMode: 'off',
  cacheDir: tmp(),
  ...over,
});
const ask = { messages: [{ role: 'user' as const, content: 'Classify: Then the user is saved' }] };

describe('C3-06 settings come only from .env (NFR8)', () => {
  test('Ollama and Hugging Face are the same code, different env', () => {
    const local = readModelConfig({
      LLM_BASE_URL: 'http://localhost:11434/v1/',
      LLM_MODEL: 'qwen2.5-coder:3b',
    });
    const hf = readModelConfig({
      LLM_BASE_URL: 'https://router.huggingface.co/v1',
      LLM_MODEL: 'Qwen/Qwen2.5-Coder-7B-Instruct:nscale',
      LLM_API_KEY: 'hf_test',
      LLM_CACHE: 'readonly',
    });
    expect(local).toMatchObject({
      baseUrl: 'http://localhost:11434/v1',
      provider: 'ollama',
      timeoutMs: 60000,
      maxRetries: 2,
      cacheMode: 'readwrite',
    });
    expect(hf).toMatchObject({ provider: 'huggingface', apiKey: 'hf_test', cacheMode: 'readonly' });
    expect(createModelClient(local).modelTag).toBe('qwen2.5-coder:3b@ollama');
    expect(createModelClient(hf).modelTag).toBe(
      'Qwen/Qwen2.5-Coder-7B-Instruct:nscale@huggingface',
    );
  });

  test('one clear error lists every missing or wrong setting', () => {
    expect(() =>
      readModelConfig({
        LLM_BASE_URL: 'https://router.huggingface.co/v1',
        LLM_TIMEOUT_MS: 'soon',
        LLM_CACHE: 'maybe',
      }),
    ).toThrow(
      /LLM_MODEL is not set[\s\S]*LLM_API_KEY is required[\s\S]*LLM_TIMEOUT_MS must be a whole number[\s\S]*LLM_CACHE must be/,
    );
  });

  test.each([
    ['http://localhost:11434/v1', 'ollama'],
    ['https://router.huggingface.co/v1', 'huggingface'],
    ['http://10.0.0.5:8000/v1', 'openai-compatible'],
  ])('%s -> %s', (url, provider) => {
    expect(providerOf(url)).toBe(provider);
  });
});

describe('C3-06 OpenAI-compatible client', () => {
  test('sends model, messages, temperature 0 and the API key; returns text, model tag and usage', async () => {
    const client = new OpenAICompatibleClient(
      cfg({ apiKey: 'hf_secret', provider: 'huggingface' }),
      noWait,
    );
    const res = await client.complete({ ...ask, json: true, maxTokens: 50 });
    expect(res).toMatchObject({
      text: 'answer 1',
      model: 'qwen2.5-coder:3b',
      provider: 'huggingface',
      cached: false,
      usage: { promptTokens: 7, completionTokens: 2 },
    });
    expect(seen[0]!.auth).toBe('Bearer hf_secret');
    expect(seen[0]!.body).toMatchObject({
      model: 'qwen2.5-coder:3b',
      temperature: 0,
      max_tokens: 50,
      response_format: { type: 'json_object' },
      stream: false,
    });
  });

  test('retries a server error (HTTP 503) and then succeeds', async () => {
    plan = (n) =>
      n < 2
        ? { status: 503 }
        : { status: 200, body: { choices: [{ message: { content: 'ok' } }] } };
    const logs: string[] = [];
    const client = new OpenAICompatibleClient(cfg(), { ...noWait, log: (l) => logs.push(l) });
    expect((await client.complete(ask)).text).toBe('ok');
    expect(seen).toHaveLength(3);
    expect(logs[0]).toMatch(/attempt 1\/3 failed \(model server answered HTTP 503/);
  });

  test('does not retry a client error (HTTP 401) and says which model and URL', async () => {
    plan = () => ({ status: 401, body: { error: 'bad token' } });
    const client = new OpenAICompatibleClient(cfg(), noWait);
    await expect(client.complete({ ...ask, purpose: 'C3-08 typing' })).rejects.toThrow(
      /C3-08 typing: model server answered HTTP 401.*bad token.*qwen2\.5-coder:3b@ollama/,
    );
    expect(seen).toHaveLength(1);
  });

  test('a slow answer times out, is retried, then fails with a clear message', async () => {
    plan = () => ({
      status: 200,
      delayMs: 300,
      body: { choices: [{ message: { content: 'late' } }] },
    });
    const client = new OpenAICompatibleClient(cfg({ timeoutMs: 50, maxRetries: 1 }), noWait);
    await expect(client.complete(ask)).rejects.toThrow(/no answer within 50 ms \(LLM_TIMEOUT_MS\)/);
    expect(seen).toHaveLength(2);
  });

  test('a server that is not running gives a helpful error', async () => {
    const client = new OpenAICompatibleClient(
      cfg({ baseUrl: 'http://127.0.0.1:9/v1', maxRetries: 0 }),
      noWait,
    );
    await expect(client.complete(ask)).rejects.toThrow(
      /cannot reach the model server.*Is Ollama running/,
    );
  });
});

describe('C3-06 answer cache (offline PP1 demo)', () => {
  test('readwrite: first call asks the server and saves; second call is answered from the file', async () => {
    const dir = tmp();
    const client = new CachedModelClient(
      new OpenAICompatibleClient(cfg(), noWait),
      dir,
      'readwrite',
    );
    const first = await client.complete({ ...ask, purpose: 'first' });
    const second = await client.complete({ ...ask, purpose: 'second label' });
    expect(first).toMatchObject({ text: 'answer 1', cached: false });
    expect(second).toMatchObject({
      text: 'answer 1',
      cached: true,
      model: 'qwen2.5-coder:3b',
      provider: 'ollama',
    });
    expect(seen).toHaveLength(1);
    const key = cacheKey('qwen2.5-coder:3b@ollama', ask);
    const saved = JSON.parse(
      fs.readFileSync(path.join(dir, key.slice(0, 2), `${key}.json`), 'utf8'),
    );
    expect(saved).toMatchObject({
      key,
      model_tag: 'qwen2.5-coder:3b@ollama',
      purpose: 'first',
      text: 'answer 1',
    });
  });

  test('readonly: a cached answer works offline; a new question fails with ModelCacheMiss', async () => {
    const dir = tmp();
    await new CachedModelClient(
      new OpenAICompatibleClient(cfg(), noWait),
      dir,
      'readwrite',
    ).complete(ask);
    const offline = new CachedModelClient(
      new OpenAICompatibleClient(cfg({ baseUrl: 'http://127.0.0.1:9/v1' }), noWait),
      dir,
      'readonly',
    );
    expect((await offline.complete(ask)).text).toBe('answer 1');
    await expect(
      offline.complete({
        messages: [{ role: 'user', content: 'new question' }],
        purpose: 'C3-07 MD-009',
      }),
    ).rejects.toBeInstanceOf(ModelCacheMiss);
    expect(seen).toHaveLength(1);
  });

  test('the key changes with model, messages or settings, not with the purpose label', () => {
    const k = cacheKey('a@ollama', ask);
    expect(cacheKey('a@ollama', { ...ask, purpose: 'x' })).toBe(k);
    expect(cacheKey('b@ollama', ask)).not.toBe(k);
    expect(cacheKey('a@ollama', { ...ask, temperature: 0.7 })).not.toBe(k);
    expect(cacheKey('a@ollama', { messages: [{ role: 'user', content: 'other' }] })).not.toBe(k);
  });

  test('createModelClient adds the cache unless LLM_CACHE=off', () => {
    expect(createModelClient(cfg({ cacheMode: 'readwrite' }))).toBeInstanceOf(CachedModelClient);
    expect(createModelClient(cfg({ cacheMode: 'off' }))).toBeInstanceOf(OpenAICompatibleClient);
  });
});

describe('C3-06 fake client and JSON answers', () => {
  test('fake client gives answers in order and records the requests (unit tests never call a model)', async () => {
    const fake = new FakeModelClient(['{"category":"equality"}', 'last']);
    expect((await fake.complete(ask)).text).toBe('{"category":"equality"}');
    expect((await fake.complete(ask)).text).toBe('last');
    expect((await fake.complete(ask)).text).toBe('last');
    expect(fake.calls).toHaveLength(3);
    expect(fake.modelTag).toBe('fake-model@fake');
  });

  test.each([
    ['{"a":1}', { a: 1 }],
    ['```json\n{"a":2}\n```', { a: 2 }],
    ['Sure! Here it is: {"a":3} Hope this helps.', { a: 3 }],
  ])('parseJsonAnswer(%j)', (text, expected) => {
    expect(parseJsonAnswer(text)).toEqual(expected);
  });

  test('parseJsonAnswer gives a clear error for non-JSON', () => {
    expect(() => parseJsonAnswer('I cannot help')).toThrow(/not valid JSON/);
    expect(new ModelError('x', 500, true).retryable).toBe(true);
  });
});

describe('C3-06 .env loading and model-check', () => {
  test('loadDotEnv reads .env but never overrides a variable that is already set', async () => {
    const { loadDotEnv } = await import('../src/model/config.js');
    const dir = tmp();
    fs.writeFileSync(path.join(dir, '.env'), 'C3_TEST_A=from-file\nC3_TEST_B=from-file\n');
    process.env.C3_TEST_B = 'from-shell';
    try {
      expect(loadDotEnv([path.join(dir, 'nothing-here'), dir])).toBe(path.join(dir, '.env'));
      expect(process.env.C3_TEST_A).toBe('from-file');
      expect(process.env.C3_TEST_B).toBe('from-shell');
    } finally {
      delete process.env.C3_TEST_A;
      delete process.env.C3_TEST_B;
    }
  });

  test('model-check sends one tiny prompt and returns the answer', async () => {
    const { modelCheck } = await import('../src/index.js');
    const saved = { url: process.env.LLM_BASE_URL, model: process.env.LLM_MODEL };
    process.env.LLM_BASE_URL = baseUrl;
    process.env.LLM_MODEL = 'qwen2.5-coder:3b';
    try {
      expect(await modelCheck()).toBe('answer 1');
      expect(seen[0]!.body.messages[0].content).toMatch(/Reply with exactly the word OK/);
    } finally {
      if (saved.url === undefined) delete process.env.LLM_BASE_URL;
      else process.env.LLM_BASE_URL = saved.url;
      if (saved.model === undefined) delete process.env.LLM_MODEL;
      else process.env.LLM_MODEL = saved.model;
    }
  });
});
