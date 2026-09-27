# Cases

Sondara's scenarios come from two real field families, a one-hole measured-survey family, and authored validation
fixtures. Each family page states its source, license and attribution, what the ingest keeps, the decisions carried
into every result, and what the family can and cannot answer.

| Family | Page | Scenarios | Real data |
|---|---|---|---|
| Rocklea Dome, CSIRO | [rocklea.md](rocklea.md) | R01 to R12 | 5,035 one-metre multielement intervals in 158 holes, assumed vertical |
| Alberta MAR_19860002, AGS | [alberta.md](alberta.md) | A01 to A08 | 22 inclined holes, 150 geology records, 176 Cu/Zn sampling envelopes |
| NTGS 12LE002 | [ntgs.md](ntgs.md) | measured-survey and QA scenarios | one hole, 11 measured stations, 1,892 determinations |
| Authored fixtures | [fixtures.md](fixtures.md) | S01 to S12, fixtures F01 to F42 | none: analytic and adversarial inputs, labelled as authored |

Run `python data-pipeline/run.py ingest --cache <raw sources>` and then `preprocess`; each family writes its canonical
project, issue table and reconciliation waterfall, then its desurveyed positions, composites, log overlay and
modeling populations, to `build/derived/<family>/`. Each family page ends with its preprocessing results.

The three authored demo cases of the 0.2 releases (Copper Ridge, North Shear, Salar Edge) are not part of this registry.
They remain in the current web page only until the web product is rebuilt on these families (unit SD-9).
