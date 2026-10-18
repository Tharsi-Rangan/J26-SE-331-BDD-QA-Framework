
import {
  AstBuilder,
  GherkinClassicTokenMatcher,
  Parser,
} from '@cucumber/gherkin';
import { IdGenerator } from '@cucumber/messages';

export interface GherkinValidationResult {
  valid: boolean;
  error?: string;
}

export function validateGherkin(
  source: string,
): GherkinValidationResult {
  try {
    const builder = new AstBuilder(IdGenerator.uuid());
    const matcher = new GherkinClassicTokenMatcher();
    const parser = new Parser(builder, matcher);

    const document = parser.parse(source);
    const feature = document.feature;

    if (!feature) {
      return {
        valid: false,
        error: 'Gherkin document does not contain a Feature',
      };
    }

    if (!feature.children || feature.children.length === 0) {
      return {
        valid: false,
        error: 'Feature does not contain any scenarios or rules',
      };
    }

    return { valid: true };
  } catch (error) {
    return {
      valid: false,
      error:
        error instanceof Error
          ? error.message
          : 'Unknown Gherkin parsing error',
    };
  }
}
