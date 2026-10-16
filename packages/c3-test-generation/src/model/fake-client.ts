// C3-06 fake model for unit tests: no network, no cost, same answer every time.
import type { ModelClient, ModelRequest, ModelResponse } from './types.js';

export type FakeResponder = (request: ModelRequest, callIndex: number) => string;

export class FakeModelClient implements ModelClient {
  readonly modelTag: string;
  readonly calls: ModelRequest[] = [];

  /**
   * @param answers a function that builds the answer, or a list of answers given in order
   *                (the last one repeats when the list runs out)
   */
  constructor(answers: FakeResponder | string[], modelTag = 'fake-model@fake') {
    this.modelTag = modelTag;
    this.respond =
      typeof answers === 'function'
        ? answers
        : (_req, i) => answers[Math.min(i, answers.length - 1)] ?? '';
  }

  private readonly respond: FakeResponder;

  async complete(request: ModelRequest): Promise<ModelResponse> {
    const i = this.calls.length;
    this.calls.push(request);
    const at = this.modelTag.lastIndexOf('@');
    return {
      text: this.respond(request, i),
      model: this.modelTag.slice(0, at),
      provider: this.modelTag.slice(at + 1),
      cached: false,
      latencyMs: 0,
    };
  }
}
