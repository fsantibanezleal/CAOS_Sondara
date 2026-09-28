# Sondara · software design document (product)

Written 2026-09-26. Sondara was instantiated on 2026-09-10, before the design-document gate (ADR-0075) existed; the
first three pipeline stages (0.03.000 and 0.04.000) were built from the research dossiers and the plan. This document
records the design those stages follow and the design of everything still to build, and it is the review target from
here on. Each non-trivial unit adds a feature design under `docs/design/features/<slug>/` (requirements in EARS,
design, tasks) before its code, and every requirement names the gate that verifies it.

The research is persisted in the management repository (`wip/drillhole-workbench/`): methods, data, architecture,
learned and probabilistic methods, the content and data contract, the package boundary and the implementation plan.
The plan and build sequence are in `plans/sondara/`.

## 1. Problem

Drillhole data arrive as separate collar, survey, assay and geology tables, from several files and sources, with
inconsistent identifiers, units, angle conventions, sampling supports and censoring. Before any estimate, a geologist
needs to know which holes are usable, where each sample actually is, what support each value has, and which
decisions were made to get there. After that, the questions are geostatistical: is continuity directional, what does
support change, does a secondary variable help, can an entire withheld hole be predicted, and which geological
connections survive alternative priors.

Sondara answers them on real public data, with every step visible and reproducible:

1. **Import and QA.** Multi-file collar, survey, assay and geology import as a reviewable transaction, with conflicts,
   orphans, pending companions and exclusions reported rather than resolved silently.
2. **Geometry and support.** Minimum-curvature desurvey from what each source actually supports, support positions,
   length-weighted compositing that keeps coverage, and log overlays that keep conflicts.
3. **Estimation and simulation.** Twelve prediction and simulation methods (NN, IDW, SK, OK, UK, LMC cokriging, MIK,
   SGS, SNESIM, Direct Sampling, DeepKriging, KCN) and a separate geochemical autoencoder diagnostic, compared on
   identical targets with sealed grouped holdouts.
4. **A linked workbench.** Traces, sections, logs, variograms, estimates and realizations linked to the same
   observations, in the browser, with imports that never leave the machine unless the user submits a server job.

## 2. Non-goals

- **Not a resource or reserve estimate.** No classification, no economic evaluation, no competent-person statement.
  Results are method comparisons on declared supports.
- **No invented data.** No fabricated collars, survey stations, sample weights, lithology or grades. A source that
  cannot support a task is excluded from it with its reason, and the exclusion is shown.
- **No geodetic reprojection where the datum is unresolved.** Rocklea's metric grid stays local; Alberta's azimuth
  reference stays unknown; NTGS is local ENU anchored at a declared collar.
- **No login and no accounts.** Server jobs are anonymous, capability-protected and expiring.
- **Not a GIS or a general database.** Import handles drillhole tables; it does not manage spatial layers or users.
- **No internal package.** Reusable numerics are the published GeoCond package; product code is plain scripts.
- **Neural fields are not block grades.** DeepKriging and KCN estimate interval centres; they are never presented as
  support-integrated block estimates.

## 3. Components

| Component | Where | Role |
|---|---|---|
| GeoCond (Python) | separate repository, published on PyPI | geometry, supports, compositing, covariance and LMC, variograms, kriging and cokriging, MIK, SGS, Direct Sampling, float64 CUDA lanes |
| MPSlib (C++) | pinned upstream source, compiled locally | SNESIM (tree and list), run as a supervised subprocess |
| pipeline | `data-pipeline/` here, plain scripts run by path | acquire, ingest (source adapters and the generic importer), preprocess, dataset, features, train, infer, evaluate, export, validate |
| learned models | `data-pipeline/learned/` | DeepKriging, KCN and the autoencoder in PyTorch, with ONNX export |
| web | `frontend/` here | six pages on the shared shell; the workbench; the local import worker; ONNX and JS kriging lanes |
| API | `app/` here | the bounded `sondara.job/v1` server lane on the ML VPS |
| wiki | `docs/` here | cases, architecture, frameworks, guides and this design |

## 4. Contracts

### 4.1 Ingestion (raw to pipeline)

| Source | Form | Checks | Policy for bad records |
|---|---|---|---|
| Rocklea, Alberta, NTGS | files pinned in `data/sources/manifest.json` by URL or bundled path, bytes and SHA-256, with license and attribution | byte count and hash on every acquire; adapters raise on any count drift from the dossiers | quarantined with an issue code and the affected rows; never repaired |
| User files | an import manifest `drillhole.import/v1` naming each file's role, dialect, encoding, missing tokens, units, column map, angle convention and namespace | declared parsing, header and row integrity, unit conversion, CRS agreement, identity, joins, conflicts | the transaction reports every finding by file, role, hole, severity and reason; errors block acceptance until resolved in the manifest; exclusions are listed |

### 4.2 Canonical project (`drillhole.project/v1`)

Frames, collars, surveys (with roles), trajectories (with kind), analytes, supports (`interval`, `sampling-envelope`,
`point`, `unknown`), determinations (value, raw token, qualifier, detection limit, state, method, lab), geology
(intervals and events, verbatim), issues and the reconciliation waterfall. Every row keeps its source row identity.
`scripts/check_artifacts.py` enforces the contract.

### 4.3 Preprocessed output (`drillhole.preprocessed/v1`)

Desurveyed trajectories, support positions, composites with coverage and parents, log overlays with conflicts, gaps,
repeats, censoring and the modeling populations, bound to the input project by hash.

### 4.4 Artifact (pipeline to web)

Arrow and Parquet tables for observations, composites, targets, estimates and realizations; typed geometry; tiled
scalar and category fields; the model registry; metrics; and an immutable manifest with hashes (unit SD-8). The web
reads only manifest-listed artifacts and verifies their hashes.

## 5. Lanes

| Lane | What runs there | Basis |
|---|---|---|
| Offline (`.venv-pipeline`, CPU) | every stage, every method, every case | the reference implementation; reproducible from the pinned sources |
| Offline (CUDA) | GeoCond float64 lanes, Direct Sampling scorer, neural training | measured on this workstation; results must equal the CPU lane within the stated tolerance |
| Browser, local | import and QA in a worker, desurvey and composite preview, linked views, ONNX inference, float64 JS kriging on bounded probes | privacy: user files never leave the machine; enabled per method only after Python parity and a measured runtime gate |
| Server (ML VPS) | bounded jobs the browser cannot run: compiled SNESIM, larger kriging and simulation grids | provisional limits from the research (one active job, 2 GiB worker memory, 25 MiB input, 128 MiB expanded, 24 h retention), to be measured on the host before release |

## 6. Methods and their acceptance criteria

| Method | Engine | Accepted when |
|---|---|---|
| Minimum-curvature desurvey | GeoCond `geometry` | welleng parity within 1e-9 of the path length; analytic endpoints; the NTGS audit figures reproduced |
| Compositing and overlay | GeoCond `compositing` | exact conservation; coverage and residual rules; the Alberta overlay audit reproduced |
| Directional variograms | GeoCond `variogram` | identical bins to the all-pair oracle and GSTools on the field composites |
| NN and IDW | GeoCond `baselines` | identical observations and targets as kriging; no variance reported |
| SK, OK, UK | GeoCond `kriging` | gstat and PyKrige parity on fixed models; train-only fitted models on the field splits |
| LMC cokriging | GeoCond `kriging`, `variogram` | PSD sill matrices; zero-cross reduction to univariate; matched holdout errors reported whether better or worse |
| MIK | GeoCond `probability` | order-corrected CDF against the isotonic oracle; held-out probability scores |
| SGS | GeoCond `simulation` | hard-data honor; reproduction of the normal-score histogram and variogram over realizations |
| SNESIM | MPSlib, subprocess | hard-data honor; seed reproducibility; exact small-pattern frequencies |
| Direct Sampling | GeoCond `direct_sampling` | CPU and CUDA candidate identity; hard-data honor; seeded structure |
| DeepKriging, KCN | PyTorch, ONNX | sealed grouped holdout against the classical methods on identical targets; coordinate-only and shuffled-label controls; CPU, CUDA and ONNX parity |
| Autoencoder | PyTorch, ONNX | held-out reconstruction against matched PCA; controlled perturbations labelled as such |

## 7. Cases and coverage

| Group | Why it exists |
|---|---|
| Rocklea R01 to R12 | the only family with complete multielement values on known 1 m support: grade, support, anisotropy, neighbourhood, cokriging, holdout and learned-method questions |
| Alberta A01 to A08 | inclined holes with logged geology and native sampling envelopes: support QA, envelope-centre approximation, lithology overlay and categorical simulation under labelled priors |
| NTGS 12LE002 | the only measured curved trajectory: desurvey, interval logs, censoring and repeats; excluded from estimation by design |
| Authored S01 to S12 | analytic and adversarial truths the field data cannot supply |
| Fixtures F01 to F42 | the importer and QA catalogue: each has a construction and an expected outcome, and each is verified by the stage that owns it |

Categorical methods take categorical inputs and continuous methods continuous inputs; a capability matrix marks
unsupported combinations explicitly. Every applicable method and case cell must be computed before release.

## 8. The oracle

Correctness is decided by independent references, not by agreement with ourselves: analytic solutions (arc
geometry, conservation, constant and polynomial kriging truth), R/gstat, PyKrige, GSTools, welleng, scikit-learn and
exhaustive enumeration for small categorical patterns. Field prediction quality is decided by sealed grouped holdouts
(whole holes and spatial margins) on real assays, evaluated once. The research audits fix the expected source counts.
Limitation: a field holdout measures prediction of withheld assays, not geological truth between holes; it is stated
as such.

## 9. Deploy driver

The web is static and served by the ML VPS mirror of the Pages build; it stays static until a server job is needed.
A method moves to the server lane when its measured browser run on the declared case exceeds 10 s or 1 GiB, or when it
needs a compiled engine (SNESIM). The server job limits are UNDECIDED until measured on the host (unit SD-10).

## 10. Risks and kill criteria

- **Covariance or support checks fail.** No field-estimation claim advances while any gstat, PyKrige or quadrature
  check fails.
- **Direct Sampling CPU and CUDA diverge.** The CUDA lane is withdrawn, not relabelled, until candidate identity holds.
- **Learned methods lose to the baselines.** The result is published as measured; no neural selector is enabled
  without real checkpoints and ONNX parity.
- **Source semantics change upstream.** Acquisition fails on the hash; the adapters' count gates fail on drift.
- **Browser limits.** A lane that cannot meet its measured gate stays offline or server-side, labelled.

## 11. Requirements in force

```
R-001  THE repository SHALL contain no em-dash and no emoji in any tracked text file.
       Gate: scripts/check_content_standards.py

R-002  THE continuous-integration workflows SHALL run only cheap checks, trigger only on develop and main, and never
       train a model.
       Gate: scripts/check_ci_budget.py

R-003  IF any template example or placeholder survives instantiation, THEN THE guards SHALL fail.
       Gate: scripts/check_template_residue.py

R-004  THE repository SHALL keep a design document in which every requirement names a gate that exists.
       Gate: scripts/check_sdd.py

R-005  WHEN a feature's requirements open with "Status: planned", THE SDD gate SHALL still require SHALL and a gate
       naming a repository file for each of them, SHALL list and count them apart from the live requirements, and
       SHALL NOT accept the status on the design document itself.
       Gate: tests/test_sdd.py::test_planned_requirements_are_counted_apart

R-010  THE sources manifest SHALL pin every source file by URL or bundled path, byte count and SHA-256, with its
       license and attribution.
       Gate: tests/test_ingest.py::test_the_manifest_pins_every_source_with_license_and_attribution

R-011  IF a source's byte count or SHA-256 differs from the manifest, THEN THE acquire stage SHALL refuse it and write
       nothing for it.
       Gate: tests/test_ingest.py::test_acquire_refuses_a_changed_source

R-012  THE Rocklea ingest SHALL reconcile 17,474 workbook intervals to 7,240 with a unique source collar, 5,035
       eligible intervals and 158 holes, quarantining the 2,205 all-analyte-zero rows.
       Gate: tests/test_ingest.py::test_rocklea_reconciles_to_the_dossier_population

R-013  THE Alberta ingest SHALL keep 176 sampling envelopes with unknown weights, 162 point supports and 4 unknown
       supports, and SHALL NOT treat an envelope as a uniform interval.
       Gate: tests/test_ingest.py::test_alberta_keeps_native_sampling_support

R-014  THE NTGS ingest SHALL keep the 850 below-detection results as a qualifier and a limit with no numeric value.
       Gate: tests/test_ingest.py::test_ntgs_is_one_measured_hole_with_censoring_kept_as_qualifiers

R-015  WHEN a family is ingested twice from the same sources, THE ingest SHALL produce the same project hash.
       Gate: tests/test_ingest.py::test_ingest_writes_a_hashed_project_and_summary

R-016  IF an ingested project violates the canonical contract, THEN THE artifact check SHALL fail and name the
       violation.
       Gate: tests/test_ingest.py::test_the_contract_check_accepts_the_ingest_and_rejects_each_corruption

R-020  THE preprocess stage SHALL composite only known continuous intervals, keep coverage and parents, give no mean
       to a composite below the declared coverage, label residuals, and conserve every grade-length integral per hole.
       Gate: tests/test_preprocess.py::test_authored_compositing_positions_and_statuses

R-021  THE preprocess stage SHALL reproduce the Rocklea composite populations and the native values at 1 m.
       Gate: tests/test_preprocess.py::test_rocklea_composites_reproduce_and_conserve

R-022  WHEN logs with two different known codes cover one depth, THE overlay SHALL record a conflict and count that
       length as not covered by a known code.
       Gate: tests/test_preprocess.py::test_authored_overlay_flags_conflicts_and_unknown_codes

R-023  THE Alberta overlay SHALL reproduce the audit: 173, 51 and 36 fully covered envelopes and 1,960.1, 285.6 and
       207.4 m covered.
       Gate: tests/test_preprocess.py::test_alberta_overlay_and_populations_match_the_dossier

R-024  THE NTGS trajectory SHALL reproduce the audit's largest dogleg within 1e-9 degrees and its departure from the
       collar direction within 1e-6 m.
       Gate: tests/test_preprocess.py::test_ntgs_trajectory_gaps_and_repeats_match_the_dossier

R-025  IF a preprocessed output does not match its project, THEN THE artifact check SHALL fail and name the violation.
       Gate: tests/test_preprocess.py::test_the_contract_check_rejects_each_preprocess_corruption

R-026  IF a project does not match its ingest summary, THEN THE preprocess stage SHALL refuse it.
       Gate: tests/test_preprocess.py::test_preprocess_refuses_a_changed_project
```
