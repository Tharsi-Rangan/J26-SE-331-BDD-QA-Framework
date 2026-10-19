// C3-06 model client types (NFR8: switching model = .env change only).
// Every model call in C3 (C3-07 mock behaviour, C3-08 assertion typing, C3-12 repair) goes through
// ModelClient, so tests can use FakeModelClient and the PP1 demo can run from the answer cache.

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

export interface ModelRequest {
  messages: ChatMessage[];
  temperature?: number; // default 0 (repeatable answers)
  maxTokens?: number;
  /** Ask for a JSON object answer (OpenAI `response_format: json_object`). */
  json?: boolean;
  /** Short label for logs, e.g. 'C3-07 behaviour MD-001'. Not sent to the model, not part of the cache key. */
  purpose?: string;
}

export interface ModelResponse {
  text: string;
  model: string; // e.g. 'Qwen/Qwen2.5-Coder-7B-Instruct:nscale'
  provider: string; // 'huggingface' | 'ollama' | 'openai-compatible' | 'fake'
  cached: boolean;
  latencyMs: number;
  usage?: { promptTokens?: number; completionTokens?: number };
}

export interface ModelClient {
  /** '<model>@<provider>', written into contract files (producer.model / behaviour.model). */
  readonly modelTag: string;
  complete(request: ModelRequest): Promise<ModelResponse>;
}

export class ModelError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
    public readonly retryable = false,
  ) {
    super(message);
    this.name = 'ModelError';
  }
}

/** Offline mode (LLM_CACHE=readonly) and the answer is not in the cache. */
export class ModelCacheMiss extends ModelError {
  constructor(
    public readonly key: string,
    purpose?: string,
  ) {
    super(
      `no cached model answer for ${purpose ?? 'this request'} (key ${key.slice(0, 12)}); ` +
        `run once online with LLM_CACHE=readwrite to record it`,
    );
    this.name = 'ModelCacheMiss';
  }
}
