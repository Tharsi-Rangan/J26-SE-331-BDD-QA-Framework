// C3-06: model settings come ONLY from environment variables (.env), never from code.
//   LLM_BASE_URL  http://localhost:11434/v1 (Ollama) or https://router.huggingface.co/v1 (Hugging Face)
//   LLM_MODEL     qwen2.5-coder:3b (dev) or Qwen/Qwen2.5-Coder-7B-Instruct:nscale (official runs)
//   LLM_API_KEY   hf_... for Hugging Face; any text for Ollama
//   LLM_TIMEOUT_MS (default 60000), LLM_MAX_RETRIES (default 2)
//   LLM_CACHE     readwrite (default) | readonly (offline demo) | off
//   LLM_CACHE_DIR folder for cached answers (default: <c3 package>/model-cache)
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export type CacheMode = 'readwrite' | 'readonly' | 'off';

export interface ModelConfig {
  baseUrl: string;
  model: string;
  apiKey?: string;
  provider: string;
  timeoutMs: number;
  maxRetries: number;
  cacheMode: CacheMode;
  cacheDir: string;
}

export const PACKAGE_DIR = fileURLToPath(new URL('../..', import.meta.url));
export const DEFAULT_CACHE_DIR = path.join(PACKAGE_DIR, 'model-cache');

/** 'huggingface' | 'ollama' | 'openai-compatible', from the base URL. Recorded with every answer. */
export function providerOf(baseUrl: string): string {
  let host = '';
  try {
    const u = new URL(baseUrl);
    host = `${u.hostname}:${u.port}`;
  } catch {
    return 'openai-compatible';
  }
  if (host.includes('huggingface.co')) return 'huggingface';
  if (host.endsWith(':11434')) return 'ollama';
  return 'openai-compatible';
}

/** Read the model settings. Throws one clear error listing everything that is missing or wrong. */
export function readModelConfig(env: NodeJS.ProcessEnv = process.env): ModelConfig {
  const problems: string[] = [];
  const baseUrl = env.LLM_BASE_URL?.trim() ?? '';
  const model = env.LLM_MODEL?.trim() ?? '';
  if (!baseUrl) problems.push('LLM_BASE_URL is not set');
  else {
    try {
      new URL(baseUrl);
    } catch {
      problems.push(`LLM_BASE_URL is not a valid URL: ${baseUrl}`);
    }
  }
  if (!model) problems.push('LLM_MODEL is not set');
  const provider = providerOf(baseUrl);
  const apiKey = env.LLM_API_KEY?.trim() || undefined;
  if (provider === 'huggingface' && !apiKey) {
    problems.push(
      'LLM_API_KEY is required for Hugging Face (a token with "Inference Providers" permission)',
    );
  }
  const int = (name: string, def: number) => {
    const raw = env[name]?.trim();
    if (!raw) return def;
    const n = Number(raw);
    if (!Number.isInteger(n) || n < 0)
      problems.push(`${name} must be a whole number, got "${raw}"`);
    return n;
  };
  const timeoutMs = int('LLM_TIMEOUT_MS', 60_000);
  const maxRetries = int('LLM_MAX_RETRIES', 2);
  const cacheRaw = (env.LLM_CACHE?.trim() || 'readwrite').toLowerCase();
  if (!['readwrite', 'readonly', 'off'].includes(cacheRaw)) {
    problems.push(`LLM_CACHE must be readwrite, readonly or off, got "${cacheRaw}"`);
  }
  if (problems.length) {
    throw new Error(
      `C3 model settings (.env) problems:\n  - ${problems.join('\n  - ')}\n` +
        `  See packages/c3-test-generation/.env.example`,
    );
  }
  return {
    baseUrl: baseUrl.replace(/\/+$/, ''),
    model,
    apiKey,
    provider,
    timeoutMs,
    maxRetries,
    cacheMode: cacheRaw as CacheMode,
    cacheDir: env.LLM_CACHE_DIR?.trim()
      ? path.resolve(env.LLM_CACHE_DIR.trim())
      : DEFAULT_CACHE_DIR,
  };
}

/**
 * Load `.env` into process.env (variables already set win). Looks in the folder the command was run
 * from, then the C3 package folder. Uses Node's built-in loader, so no extra package is needed.
 */
export function loadDotEnv(
  dirs: string[] = [process.env.INIT_CWD ?? process.cwd(), PACKAGE_DIR],
): string | undefined {
  for (const dir of dirs) {
    const file = path.join(dir, '.env');
    if (fs.existsSync(file)) {
      const before = { ...process.env };
      process.loadEnvFile(file);
      for (const [k, v] of Object.entries(before)) process.env[k] = v; // keep values set outside .env
      return file;
    }
  }
  return undefined;
}
