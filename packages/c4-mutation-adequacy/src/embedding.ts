/** Turns texts into vectors. One vector per text, in the same order. */
export type Embedder = (texts: string[]) => Promise<number[][]>;

/** Call the `/embeddings` route of an OpenAI-compatible server (the shared SH-07 endpoint). */
export function openAiEmbedder(baseUrl: string, model: string): Embedder {
  const url = baseUrl.replace(/\/+$/, '') + '/embeddings';
  return async (texts) => {
    if (texts.length === 0) return [];
    let res: Response;
    try {
      res = await fetch(url, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ model, input: texts }),
      });
    } catch (err) {
      throw new Error(`Cannot reach the embedding server at ${url}: ${(err as Error).message}`);
    }
    if (!res.ok)
      throw new Error(`Embedding server ${url} returned ${res.status}: ${await res.text()}`);
    const body = (await res.json()) as { data: { index: number; embedding: number[] }[] };
    return [...body.data].sort((a, b) => a.index - b.index).map((d) => d.embedding);
  };
}

/** Read `LLM_BASE_URL` and `EMBEDDING_MODEL` (see `.env.example`). */
export function embedderFromEnv(env = process.env): { embed: Embedder; model: string } {
  const baseUrl = env.LLM_BASE_URL;
  const model = env.EMBEDDING_MODEL;
  if (!baseUrl || !model)
    throw new Error('Set LLM_BASE_URL and EMBEDDING_MODEL to use an embedding trace signal');
  return { embed: openAiEmbedder(baseUrl, model), model };
}

export function cosine(a: number[], b: number[]): number {
  let dot = 0;
  let na = 0;
  let nb = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    na += a[i] * a[i];
    nb += b[i] * b[i];
  }
  return na === 0 || nb === 0 ? 0 : dot / Math.sqrt(na * nb);
}
