# Rocklea Dome: real multielement assays, assumed-vertical holes

**Source.** CSIRO, Rocklea Dome 3D Mineral Mapping Test Data Set (Rocklea Dome C3DMM), published 2020-06-04,
doi:10.25919/5ed83bf55be6a, CC BY 4.0. The data-description paper is Laukamp, Haest and Cudahy (2021), *Earth System
Science Data* 13, 1371-1386, doi:10.5194/essd-13-1371-2021. The channel iron deposit was drilled with reverse
circulation holes; the paper reports XRF weight percentages of FeO, P, S, SiO2, Al2O3, Mn, CaO, K2O, MgO and TiO2 on
1 m samples by Kalassay Ltd, and loss on ignition at 1000 C.

**Files used.** Three of the collection's 47 files, fetched by their stable CSIRO file IDs and checked by SHA-256
(`data/sources/manifest.json`): the assay workbook `Rocklea_Assay_MMX.xlsx` (1,828,032 bytes), the hyperspectral
export `RC_data_tsgexport.CSV` (1,428,944 bytes), which supplies each hole's coordinates, and the terrain and collar
points `dem_plus_collars.csv` (2,862,387 bytes), which supply elevations.

## What the ingest does, and why

| Step | Count | Rule |
|---|---|---|
| Workbook intervals | 17,474 | 500 hole IDs, original `From`/`To` support, no duplicate or non-positive intervals |
| With a unique source collar | 7,240 | a hole's TSG coordinates match exactly one terrain point within 0.51 m (all 192 mapped holes match within 0.20 m); no interpolation, no invented collars |
| Not zero in every analyte | 5,035 | 2,205 mapped rows are zero in every column: an absent analysis, not a measured zero grade; quarantined |
| Holes | 158 | the other 34 mapped holes have no eligible interval |

The 5,035 intervals are one metre each, in 158 holes (6 to 54 intervals per hole), with positive Fe, SiO2 and Al2O3 on
every row, and complete values for the eleven nonconstant analytes: Fe, P, S, SiO2, Al2O3, Mn, CaO, K2O, MgO, TiO2 and
LOI. The row identities are pinned by a hash, so a change in the source or the rule is caught.

## Decisions carried into every result

- **Trajectories are assumed vertical.** The collection holds no station surveys; a third-party workflow's
  `survey.csv` was authored as vertical. The label `assumed-vertical` travels with every derived interval.
- **The horizontal datum is unresolved.** The terrain raster declares WGS84 / UTM 50S; a third-party notebook uses
  AGD84 / AMG50. The frame is the source's metric grid, declared local, with no EPSG code and no basemap.
- **Maximum assay depth is an observed extent, not a total depth.** Total depth is null.
- **Four columns are dropped from the analytes:** Fe2o3, MnO, Na2O and LOI-100 are zero on the whole eligible
  population. An element and its oxide are not independent information.
- **The iron column is named Fe in the workbook and FeO in the paper.** The values keep the workbook name; the
  difference is an issue, and no conversion is made.
- **The TSG export is a separate source.** Its assay-like columns are not treated as new assays; it contributes
  coordinates only.

## What it can and cannot answer

Rocklea supplies the grade and multivariable scenarios (R01 to R12): whole-hole and spatial-margin holdouts over 158
groups, composite-length changes, directional continuity, Fe with SiO2 and Al2O3 cokriging, and the eleven-feature
autoencoder review. It cannot supply measured survey geometry, a geodetic placement or any observed lithology.
