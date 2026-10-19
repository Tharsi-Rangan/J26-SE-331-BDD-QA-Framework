
import { afterEach, describe, expect, test, vi } from 'vitest';
import { generateWithLlm } from '../src/llm-client.js';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('generateWithLlm', () => {
  test('sends a chat completion request and returns its content', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          choices: [
            { message: { content: 'Feature: Registration' } },
          ],
        }),
        { status: 200 },
      ),
    );

    vi.stubGlobal('fetch', fetchMock);

    const result = await generateWithLlm(
      [{ role: 'user', content: 'Generate Gherkin' }],
      {
        baseUrl: 'http://localhost:11434/v1',
        model: 'test-model',
      },
    );

    expect(result).toBe('Feature: Registration');
    expect(fetchMock).toHaveBeenCalledOnce();

    const [url, init] = fetchMock.mock.calls[0] as [
      URL,
      RequestInit,
    ];

    expect(String(url)).toBe(
      'http://localhost:11434/v1/chat/completions',
    );
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toMatchObject({
      model: 'test-model',
      temperature: 0.2,
    });
  });

  test('rejects missing model configuration', async () => {
    await expect(
      generateWithLlm(
        [{ role: 'user', content: 'Generate Gherkin' }],
        { baseUrl: 'http://localhost:11434/v1', model: '' },
      ),
    ).rejects.toThrow('Missing LLM_MODEL configuration');
  });

  test('reports HTTP errors', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response('Unavailable', { status: 503 }),
      ),
    );

    await expect(
      generateWithLlm(
        [{ role: 'user', content: 'Generate Gherkin' }],
        {
          baseUrl: 'http://localhost:11434/v1',
          model: 'test-model',
        },
      ),
    ).rejects.toThrow('LLM request failed with HTTP 503');
  });

  test('rejects empty model responses', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            choices: [{ message: { content: '   ' } }],
          }),
          { status: 200 },
        ),
      ),
    );

    await expect(
      generateWithLlm(
        [{ role: 'user', content: 'Generate Gherkin' }],
        {
          baseUrl: 'http://localhost:11434/v1',
          model: 'test-model',
        },
      ),
    ).rejects.toThrow('LLM returned an empty or invalid response');
  });
});
