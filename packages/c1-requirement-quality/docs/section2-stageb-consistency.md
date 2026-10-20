# Section 2 Stage B: consistency and contextual evidence

The deterministic analyser is authoritative for supported text rules. Effective
consistency additionally consumes explicitly adopted, complete human reviews;
v1 audit-only records have no gate effect. Confirmed conflicts take Tier 3
precedence, activate escalation, prevent Tier 1 and block BDD readiness. Approval
does not override these checks. C2 reads only `bdd_ready: true` rows and uses
`final_text`; its reader does not independently reproduce C1's analysis.

## Decision rules

Number words zero through twenty are recognized only inside numeric comparisons
with known units and the supported complete policy-definition templates. Source
strings and evidence offsets are unchanged. Compound numbers, signs, scientific
notation, unknown units, general paraphrases and role equivalence are not inferred.

Ordinary bounds retain interval semantics: `at most 3` and `at most 5` can overlap.
Two explicit assignments to the same maximum/minimum parameter, or two otherwise
identical permissions to borrow/hold/reserve a maximum number of books/loans/items
at a time, establish a policy definition. Different values produce an internal
`policy_definition_disagreement`. Exact policy values use decimal arithmetic.
Actors, predicates, objects, units and conditions must match the supported
template literally. The rule chooses neither value and makes no claim that the
underlying count intervals are disjoint. Unsupported comparisons remain reviewable.

The shared v1 contract receives existing `conflict`, a failed consistency check,
both IDs and a quoted explanation. No new schema fields/enums are published.
The internal conflict kind distinguishes policy disagreements from contradictions.
Consumers of the shared status alone, and existing export-summary counters named
`contradictions`, can therefore include these policy disagreements. Consult the
quoted explanation/internal diagnostics for the distinction; the ready-only C2
handoff remains blocked for both categories.

## Context provenance and human review

`context_evidence.py` verifies archived source and normalized-ingestion hashes,
then deterministically re-ingests the DOCX to check context/requirement records,
physical source blocks and normalized text. Only unique original requirement
labels whose source coordinates/text match the authenticated artifact can bind
a pair. A contextual paragraph must explicitly reference both labels. C-04 is
not special-cased by its number or wording. It is not a standalone requirement,
a selected policy value or an independently authoritative contradiction proof.

The existing Textual form receives `CONTEXT:C-04` through its normal evidence
selection list. Both original source requirement references remain mandatory.
Selected context quotations, source identity, paragraph/section metadata and
hashes are retained in the review digest and verified again on workflow/session
replay. The normalized-source hash in the base pair binding covers the complete
context corpus; optional display citations do not change that base binding.
Unrelated context and model scores never enter the analyser.

## Compatibility and remaining limits

The deterministic consistency policy has a new fingerprint in pair-review
bindings. Historical reviews remain stored; obsolete bindings cannot silently
clear gates. Saved artifacts are not automatically reprocessed or overwritten.
No grounding policy, retriever, model asset/loading path or chunking rule changes.

Context citations currently support DOCX paragraphs with explicit references to
both original labels. Tables, implicit context relevance and other formats are
not inferred. Re-ingestion can reject context produced by an older/different
ingestion policy; explicit fresh processing is required. Hashes detect changes,
not coordinated replacement of a complete bundle or authenticated authorship.

Human-confirmed conflicts remain sticky under the pre-existing effective policy.
There is no dedicated adjudication operation that clears those review records;
this stage does not force an automatic resolution. Corrected texts still require
the existing clarification, grounding, explicit escalation-resolution and review
gates. A pair-level result does not establish whole-document consistency.
The analyser receives requirement IDs and text, rather than a section-scope or
actor ontology. Scope inherited from headings, external role definitions or
unstated exceptions is not established by this rule; these need human review.

Pair enumeration remains quadratic. Numeric recognition adds bounded regex work
per comparison. Verified context adds source hashing and DOCX re-ingestion when
requested or when replaying context-bearing reviews, per verified snapshot.
Selecting citations scans the contextual paragraphs for each pair, adding
O(pairs × context paragraphs) reference checks and proportional citation storage.
It introduces no model inference, network access, vector index or new dependency.
No general retrieval/consistency accuracy or peak-RAM claim follows from these tests.

## Verification at completion (2026-10-20)

The final focused run passed 137 tests in 28.41 seconds. It covered policy and
context regressions, existing deterministic/effective consistency, human review
and DOCX semantics. The subsequent full C1 suite passed 1,435 tests in 1,410.61
seconds (23:30), with no failures or skips. These counts overlap. Runs used fresh
temporary directories, the existing environment, offline Hub settings and test
doubles rather than real model inference.

A deterministic probe of the original Mini Library DOCX compared checkpoint
`bc8d95c` with the final implementation. Its 13 requirements and four context
records yielded 78 pairs: LIB-007/LIB-008 changed from `unassessed` to a policy
definition disagreement; 77 other pairs remained unassessed. Two requirements
were Tier 3, eleven were Tier 2 and none was BDD-ready. Verified `CONTEXT:C-04`
was selectable, and the source bytes remained unchanged. Their SHA256 was
`539501273a5c0eb5130c68ea72f61615cff93a45b92c85355bd54d54ccd7e452`.

The shared contract validator passed for the fresh Mini Library run and the
existing complete C1–C4 golden fixture. The actual C2 `readReadyRequirements`
consumer returned zero ready rows from that run. `git diff --check` passed;
RAG, grounding, model-loading/dependency, contract and C2 implementation files
remained unchanged. No dependencies were installed, model weights downloaded or
loaded, or cloud services called. No commit or push was performed. Stage C
remains subject to user review.
