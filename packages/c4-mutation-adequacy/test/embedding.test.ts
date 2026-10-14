import { afterEach, describe, expect, test, vi } from 'vitest';
import { cosine, embedderFromEnv, openAiEmbedder } from '../src/embedding.js';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('c4 embedding client', () => {
  test('posts to /embeddings and returns vectors in input order', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          data: [
            { index: 1, embedding: [0, 1] },
            { index: 0, embedding: [1, 0] },
          ],
        }),
      ),
    );
    vi.stubGlobal('fetch', fetchMock);

    const out = await openAiEmbedder('http://localhost:11434/v1/', 'nomic-embed-text')(['a', 'b']);
    expect(out).toEqual([
      [1, 0],
      [0, 1],
    ]);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://localhost:11434/v1/embeddings');
    expect(JSON.parse(init.body)).toEqual({ model: 'nomic-embed-text', input: ['a', 'b'] });
  });

  test('a server error names the URL and the status', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('no model', { status: 404 })));
    await expect(openAiEmbedder('http://x/v1', 'm')(['a'])).rejects.toThrow(
      /http:\/\/x\/v1\/embeddings returned 404: no model/,
    );
  });

  test('a server that is down gives a readable error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('ECONNREFUSED')));
    await expect(openAiEmbedder('http://x/v1', 'm')(['a'])).rejects.toThrow(
      /Cannot reach the embedding server at http:\/\/x\/v1\/embeddings: ECONNREFUSED/,
    );
  });

  test('embedderFromEnv needs LLM_BASE_URL and EMBEDDING_MODEL', () => {
    expect(() => embedderFromEnv({ LLM_BASE_URL: 'http://x/v1' })).toThrow(/EMBEDDING_MODEL/);
    expect(embedderFromEnv({ LLM_BASE_URL: 'http://x/v1', EMBEDDING_MODEL: 'm' }).model).toBe('m');
  });

  test('cosine', () => {
    expect(cosine([1, 0], [1, 0])).toBe(1);
    expect(cosine([1, 0], [0, 1])).toBe(0);
    expect(cosine([0, 0], [1, 1])).toBe(0);
  });
});
