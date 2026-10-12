
export interface LlmMessage {
  role: 'system' | 'user';
  content: string;
}

export interface LlmClientOptions {
  baseUrl?: string;
  model?: string;
  timeoutMs?: number;
}

interface ChatCompletionResponse {
  choices?: Array<{
    message?: {
      content?: string;
    };
  }>;
}

export async function generateWithLlm(
  messages: LlmMessage[],
  options: LlmClientOptions = {},
): Promise<string> {
  const baseUrl =
    options.baseUrl ?? process.env.LLM_BASE_URL;
  const model =
    options.model ?? process.env.LLM_MODEL;
  const timeoutMs = options.timeoutMs ?? 60_000;

  if (!baseUrl) {
    throw new Error('Missing LLM_BASE_URL configuration');
  }

  if (!model) {
    throw new Error('Missing LLM_MODEL configuration');
  }

  let endpoint: URL;

  try {
    const normalizedBaseUrl = baseUrl.endsWith('/')
      ? baseUrl
      : `${baseUrl}/`;

    endpoint = new URL('chat/completions', normalizedBaseUrl);
  } catch {
    throw new Error('LLM_BASE_URL must be a valid URL');
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model,
        messages,
        temperature: 0.2,
      }),
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(
        `LLM request failed with HTTP ${response.status}`,
      );
    }

    const data = (await response.json()) as ChatCompletionResponse;
    const content = data.choices?.[0]?.message?.content;

    if (typeof content !== 'string' || !content.trim()) {
      throw new Error('LLM returned an empty or invalid response');
    }

    return content.trim();
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error(`LLM request timed out after ${timeoutMs} ms`);
    }

    throw error;
  } finally {
    clearTimeout(timeout);
  }
}
