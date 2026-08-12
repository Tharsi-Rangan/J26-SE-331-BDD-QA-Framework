# Trustworthy Requirement-Traceable QA Framework for BDD Test Generation

**IT4010 Research Project · 2026 Jul · Group J26-SE-331**
Faculty of Computing, Sri Lanka Institute of Information Technology

![Status](https://img.shields.io/badge/status-proposal%20stage-orange)
![Phase](https://img.shields.io/badge/phase-pre--implementation-lightgrey)



## The problem

LLMs can generate test code that compiles, executes, and passes — and still verifies the wrong behaviour. Existing tools give no way to distinguish a trustworthy test from a plausible-looking one.

We call this failure the **false-runnable test**: a test that runs successfully but does not check what its requirement actually describes. No current work measures it.

The problem compounds because each stage of the requirement-to-test pipeline is studied in isolation. Requirement-quality tools stop at labelling defects. Scenario generators validate syntax but not meaning. Test generators produce mocks without stating why. Mutation testing returns a score with no link back to what the software was supposed to do. Errors introduced early travel downstream unchallenged.

---

## What we build

Four components, each conditioned on the one before it, with an explicit trust decision at every handoff.

| | Component | Owner | Core claim |
|---|---|---|---|
| **C1** | Grounded Requirement Refinement | Jathusan J. | Separates *grounded* fixes from *fabricated* ones and reports a fabrication rate |
| **C2** | Boundary-Aware Gherkin Generation | Shanchika | Verifies scenario *meaning*, not only Gherkin syntax |
| **C3** | Runnable Test Generation | Ranganathan T. | Every mock carries a stated rationale; confidence routing decides what ships and what a human reviews |
| **C4** | Requirement-Traceable Mutation Adequacy | Shajana | Maps surviving mutants back to the originating requirement |

**Main objective.** To design and evaluate a trustworthy, requirement-traceable QA framework that grounds, verifies and conditions each stage of BDD-based test generation on the stage before it, and to measure whether end-to-end traceability improves test adequacy and defect localisation compared with independent-stage baselines.

**Central experiment.** A traceability ablation: the full conditioned pipeline against the same four stages run independently.

---

## Pipeline

```
SRS / User Stories
        │
        ▼
  C1  Grounded Requirement Refinement
        │  refined_requirements.json
        ▼
  C2  Boundary-Aware Gherkin Generation
        │  *.feature + scenario_metadata.json
        ▼
  C3  Runnable Test Generation
        │  test suites + explanation report
        ▼
  C4  Requirement-Traceable Mutation Adequacy
        │
        ▼
  Adequacy + attribution report
```

Every handoff is a JSON contract. A shared orchestrator holds pipeline state and the human-review queue. Component interfaces are defined independently of implementation language.

