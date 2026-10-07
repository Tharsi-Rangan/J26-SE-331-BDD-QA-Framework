# .feature file conventions (C2 writes, C3 reads)

- One `.feature` file per requirement, named `<REQUIREMENT-ID>.feature`.
- Feature-level tag: `@REQ-<CODE>-<nnn>` (exactly one).
- Scenario-level tags: `@SCN-<CODE>-<nnn>-<nn>` (exactly one) and `@type:<positive|negative|boundary|edge>`.
- Scenario title must equal `scenario_name` in `scenario_metadata.json`.
- Boundary/partition cases use `Scenario Outline` + `Examples`. Row order must match `examples[].row_index`.
- Step text lives only in the `.feature` file. Metadata never repeats it.
- Language: English Gherkin keywords only (`Given/When/Then/And/But`).

Example: `fixtures/golden/example-registration/c2/features/REQ-EX-001.feature`
