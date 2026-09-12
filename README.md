# Sondara

Sondara is a live drillhole scientific workbench. It combines local multi-source collar, survey, assay and geology import with linked spatial analysis, reproducible estimation and geological simulation.

The public workbench is released as a local-first application. Its visual section explorer, source loader, local estimator controls, scenario cases and reproducible data pipeline are available without login; the strict server contract remains bounded and separately gated.

The product uses the shared CAOS application shell and a separately published numerical library. It declares no internal Python distribution; product pipelines run as scripts by path.

## Current release

**v0.2.0 is live at https://sondara.ml.fasl-work.com/** and is published from the public `main` branch. The browser workbench presents a WebGL subsurface reconstruction with surveyed borehole tubes, assay supports, an ore continuity shell, geology contacts, depth slicing and orbit/section/plan views. Collar, survey, assay and geology files remain local; the estimator controls recompute the selected support-weighted estimate in the browser.

The strict `sondara.job/v1` contract remains available for a later bounded server lane. It rejects arbitrary paths, URLs and oversized jobs; heavy numerical and GPU processing stays in the local pipeline until a reviewed worker is promoted. The current public site does not claim a production resource estimate or replace QA/QC, compositing, variogram fitting or competent-person review.

