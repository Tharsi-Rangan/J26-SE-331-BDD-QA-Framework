// C3-06: one client for every OpenAI-compatible server (Ollama, Hugging Face router, vLLM, ...).
// Only fetch() from Node 22 is used, so no SDK is needed. Timeout per attempt + retries with backoff.
import type { ModelConfig } from './config.js';
import { ModelError, type ModelClient, type ModelRequest, type ModelResponse } from './types.js';

export interface HttpClientOptions {
  /** Injected in tests so retries do not really wait. */
  sleep?: (ms: number) => Promise<void>;
  fetchImpl?: typeof fetch;
  log?: (line: string) => void;
}

interface ChatCompletion {
  model?: string;
  choices?: { message?: { content?: string | null } }[];
  usage?: { prompt_tokens?: number; completion_tokens?: number };
}

export class OpenAICompatibleClient implements ModelClient {
  readonly modelTag: string;
  private readonly sleep: (ms: number) => Promise<void>;
  private readonly fetchImpl: typeof fetch;
  private readonly log: (line: string) => void;

  constructor(
    private readonly config: Pick<
      ModelConfig,
      'baseUrl' | 'model' | 'apiKey' | 'provider' | 'timeoutMs' | 'maxRetries'
    >,
    options: HttpClientOptions = {},
  ) {
    this.modelTag = `${config.model}@${config.provider}`;
    this.sleep = options.sleep ?? ((ms) => new Promise((r) => setTimeout(r, ms)));
    this.fetchImpl = options.fetchImpl ?? fetch;
    this.log = options.log ?? (() => {});
  }

  async complete(request: ModelRequest): Promise<ModelResponse> {
    const body = {
      model: this.config.model,
      messages: request.messages,
      temperature: request.temperature ?? 0,
      ...(request.maxTokens ? { max_tokens: request.maxTokens } : {}),
      ...(request.json ? { response_format: { type: 'json_object' } } : {}),
      stream: false,
    };
    const attempts = this.config.maxRetries + 1;
    let lastError: ModelError | undefined;
    for (let attempt = 1; attempt <= attempts; attempt++) {
      const started = Date.now();
      try {
        const res = await this.fetchImpl(`${this.config.baseUrl}/chat/completions`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(this.config.apiKey ? { Authorization: `Bearer ${this.config.apiKey}` } : {}),
          },
          body: JSON.stringify(body),
          signal: AbortSignal.timeout(this.config.timeoutMs),
        });
        if (!res.ok) {
          const detail = (await res.text().catch(() => '')).slice(0, 300);
          const retryable = res.status === 429 || res.status >= 500;
          throw new ModelError(
            `model server answered HTTP ${res.status} ${res.statusText}${detail ? `: ${detail}` : ''}`,
            res.status,
            retryable,
          );
        }
        const data = (await res.json()) as ChatCompletion;
        const text = data.choices?.[0]?.message?.content;
        if (typeof text !== 'string') {
          throw new ModelError('model answer has no choices[0].message.content', res.status, true);
        }
        return {
          text,
          model: this.config.model,
          provider: this.config.provider,
          cached: false,
          latencyMs: Date.now() - started,
          usage: {
            promptTokens: data.usage?.prompt_tokens,
            completionTokens: data.usage?.completion_tokens,
          },
        };
      } catch (err) {
        lastError = toModelError(err, this.config.timeoutMs);
        if (!lastError.retryable || attempt === attempts) break;
        const wait = 500 * 2 ** (attempt - 1);
        this.log(
          `[c3] model ${this.modelTag} attempt ${attempt}/${attempts} failed (${lastError.message}); retry in ${wait} ms`,
        );
        await this.sleep(wait);
      }
    }
    throw new ModelError(
      `${request.purpose ? request.purpose + ': ' : ''}${lastError!.message} (model ${this.modelTag}, ${this.config.baseUrl})`,
      lastError!.status,
      false,
    );
  }
}

function toModelError(err: unknown, timeoutMs: number): ModelError {
  if (err instanceof ModelError) return err;
  const e = err as { name?: string; message?: string; cause?: { code?: string } };
  if (e?.name === 'TimeoutError' || e?.name === 'AbortError') {
    return new ModelError(`no answer within ${timeoutMs} ms (LLM_TIMEOUT_MS)`, undefined, true);
  }
  const code = e?.cause?.code ? ` (${e.cause.code})` : '';
  return new ModelError(
    `cannot reach the model server${code}: ${e?.message ?? String(err)}. Is Ollama running / is the URL right?`,
    undefined,
    true,
  );
}
