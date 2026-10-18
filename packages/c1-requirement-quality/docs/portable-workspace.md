# Content-only portable C1 workspace

The verified Kinmail export is at `local-inference/kinmail-portable-001/` relative
to the C1 package. Its root was created by the normal Windows account. Export
copied file bytes with exclusive creation; no ACLs, owners, timestamps or source
attributes were copied or modified. New descendants inherit destination ACLs;
they may be sandbox-owned even though the workspace root is normal-user-owned.

The export contains `registry.json` and the full `run/c1/` bundle, including the
archived SRS, normalized ingestion, source manifest and workflow snapshot.
`export-verification.json` records SHA256 comparisons. Kinmail's exported
snapshot is round 0 with no parent: there are no omitted ancestors. The registry
is preserved for future extraction, not required to load this existing run.

Use these paths from the repository root:

- Input: `packages/c1-requirement-quality/local-inference/kinmail-portable-001/run/c1/validated_requirements.json`
- SRS: `packages/c1-requirement-quality/local-inference/kinmail-portable-001/run/c1/internal/source/SRS.docx`

These paths may be supplied to `propose-clarifications`, `generate-candidates`
and `refine`. Keep outputs in fresh sibling directories and keep refinement
outputs on the same drive, because workflow parent links are relative paths.
Groq requires separate explicit approval; offline portability checks mock the
transport. `refine` still needs a human-authored actions file. Empty actions in
tests only exercise persistence and are not human approvals.

For later multi-round families, copy every referenced parent while preserving
relative directory layout and exact file bytes. A standalone validated JSON is
not enough. Historical absolute source locations in the sealed metadata remain
unchanged; validation uses supplied original bytes and recorded hashes. Do not
rewrite metadata to point at the export or fabricate missing manifests.

Normal-account smoke checks (read-only):

```powershell
Get-Content .\packages\c1-requirement-quality\local-inference\kinmail-portable-001\run\c1\validated_requirements.json -TotalCount 1
Get-FileHash .\packages\c1-requirement-quality\local-inference\kinmail-portable-001\run\c1\validated_requirements.json -Algorithm SHA256
```

Expected validated JSON SHA256:
`feca46c709f2e52db3adc43d13086f15fc2be548937f6642f486aa7be99bf622`.
Run future CLI operations from the normal account and package virtual environment;
no permission or ownership changes are needed. A sandbox verification cannot
prove execution under the normal user's token; perform the smoke check there.
