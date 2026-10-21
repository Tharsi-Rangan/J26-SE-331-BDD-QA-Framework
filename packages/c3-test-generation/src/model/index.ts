// C3-06 provider-abstracted model client. Use createModelClient() everywhere in C3:
// switching between Ollama (dev) and Hugging Face (official runs) is a .env change only (NFR8).
import { CachedModelClient } from './cache.js';
import { readModelConfig, type ModelConfig } from './config.js';
import { OpenAICompatibleClient, type HttpClientOptions } from './openai-client.js';
import type { ModelClient } from './types.js';

export * from './types.js';
export { cacheKey, CachedModelClient, type CachedAnswer } from './cache.js';
export {
  loadDotEnv,
  providerOf,
  readModelConfig,
  DEFAULT_CACHE_DIR,
  type ModelConfig,
  type CacheMode,
} from './config.js';
export { FakeModelClient, type FakeResponder } from './fake-client.js';
export { OpenAICompatibleClient } from './openai-client.js';

/** The real client from .env, wrapped in the answer cache (unless LLM_CACHE=off). */
export function createModelClient(
  config: ModelConfig = readModelConfig(),
  options: HttpClientOptions = {},
): ModelClient {
  const http = new OpenAICompatibleClient(config, options);
  return config.cacheMode === 'off'
    ? http
    : new CachedModelClient(http, config.cacheDir, config.cacheMode);
}

/** Pull the first JSON object out of a model answer (models sometimes wrap it in ``` fences or text). */
export function parseJsonAnswer<T = unknown>(text: string): T {
  const fenced = /```(?:json)?\s*([\s\S]*?)```/i.exec(text);
  const body = (fenced ? fenced[1]! : text).trim();
  try {
    return JSON.parse(body) as T;
  } catch {
    const start = body.indexOf('{');
    const end = body.lastIndexOf('}');
    if (start >= 0 && end > start) {
      try {
        return JSON.parse(body.slice(start, end + 1)) as T;
      } catch {
        /* fall through */
      }
    }
    throw new Error(`model answer is not valid JSON: ${text.slice(0, 120)}`);
  }
}
