"""CSIRO field assays joined to actual source XYZ; no inferred borehole collars."""
from collections import defaultdict
from pathlib import Path

import numpy as np
import openpyxl
from scipy.spatial import cKDTree
from source_adapters.common import determination, issue, localized, project, refs, source, support
from source_io import digest, number, read_table, stable_hash

FEATURES = ['Fe', 'P', 'S', 'SiO2', 'Al2O3', 'Mn', 'CaO', 'K2O', 'MgO', 'TiO2', 'LOI']
FILES = {'Rocklea_Assay_MMX.xlsx': ('56857404', 'ea837d71a0feb2036926447f7638f5a18d1371ea0e150c937bfa55e410b2da6e'),
         'RC_data_tsgexport.CSV': ('56857422', '3db06836038139058388de9e0e6897b51a04f663c25286865e14034f868d8cff'),
         'dem_plus_collars.csv': ('56857413', 'd4a65dc093454ed04890a71e64169cad6ed863a7d8a3113124ae7c0881b66ef5')}


def normalize(cache: Path):
    sources = []
    for filename, (source_id, expected) in FILES.items():
        if digest(cache / filename) != expected:
            raise ValueError('Rocklea source hash mismatch: ' + filename)
        sources.append(source(source_id, f'https://data.csiro.au/dap/ws/v2/collections/44783/data/{source_id}',
                              'CC-BY-4.0', 'CSIRO, Rocklea Dome 3D Mineral Mapping Test Data Set',
                              expected, 'xlsx' if filename.endswith('xlsx') else 'csv',
                              'OOXML' if filename.endswith('xlsx') else 'utf-8-sig'))
    p = project('rocklea', localized('Rocklea: one-metre geochemistry', 'Rocklea: geoquímica a un metro'), sources,
                'rocklea-v1: exact workbook supports; uppercase ID join; unique XYZ within 0.51 m; all-analyte-zero quarantine; source values unchanged',
                {'id': 'rocklea-local', 'kind': 'local-metric', 'unit': 'm', 'horizontalCrs': None,
                 'verticalDatum': None, 'origin': None,
                 'assumptions': ['Source metric grid; per-file horizontal datum unresolved. No geographic reprojection.',
                                 'Vertical trajectories are explicitly assumed; no measured station surveys acquired.']})
    xyz_rows = list(read_table(cache / 'dem_plus_collars.csv'))
    xyz = np.array([[number(r[k]) for k in ('X', 'Y', 'Z')] for r in xyz_rows])
    tree = cKDTree(xyz[:, :2])
    holes = defaultdict(list)
    for row in read_table(cache / 'RC_data_tsgexport.CSV'):
        hole = row['Borehole ID'].strip().upper()
        if hole and hole != 'NULL':
            holes[hole].append(row)
    coordinates = {}
    for hole, rows in holes.items():
        positions = {(number(r['Easting']), number(r['Northing'])) for r in rows}
        if len(positions) != 1:
            raise ValueError('Conflicting TSG XY for a hole')
        position = next(iter(positions))
        neighbors = tree.query_ball_point(position, .51)
        if len(neighbors) != 1:
            raise ValueError('Ambiguous or missing source elevation; no interpolation permitted')
        index = neighbors[0]
        coordinates[hole] = (xyz[index].tolist(), refs('56857422', rows[0]['_row']) + refs('56857413', xyz_rows[index]['_row']))
    wb = openpyxl.load_workbook(cache / 'Rocklea_Assay_MMX.xlsx', read_only=True, data_only=True)
    sheet = wb['Rocklea_Assay_MMX']
    values = sheet.values
    header = next(values)
    raw = [dict(zip(header, row)) | {'_row': i} for i, row in enumerate(values, 2)]
    wb.close()
    raw_analytes = list(header[4:])
    eligible, zero, unmatched = [], [], []
    for row in raw:
        hole = str(row['Hole_ID']).strip().upper()
        if hole not in coordinates:
            unmatched.append(row['_row'])
        elif all(number(row[k]) == 0 for k in raw_analytes):
            zero.append(row['_row'])
        else:
            if not 0 <= number(row['From']) < number(row['To']):
                raise ValueError('Invalid Rocklea interval')
            eligible.append((hole, row))
    row_ids = [r['_row'] for _, r in eligible]
    if len(eligible) != 5035 or len({h for h, _ in eligible}) != 158:
        raise ValueError('Rocklea eligibility population drift')
    if stable_hash(row_ids) != '57dffbd16a03afbaf0a73c2f724018ed177a36ec1f6106a8a8db3185aa812230':
        raise ValueError('Rocklea scientific row identity drift')
    for hole in sorted({h for h, _ in eligible}):
        position, source_refs = coordinates[hole]
        extent = max(number(r['To']) for h, r in eligible if h == hole)
        p['collars'].append({'id': hole, 'sourceHoleId': hole, 'frameId': 'rocklea-local',
                             'x': position[0], 'y': position[1], 'z': position[2],
                             'totalDepth': None, 'observedDepthMax': extent, 'orientation': None,
                             'sourceRefs': source_refs})
        p['trajectories'].append({'holeId': hole, 'kind': 'assumed-vertical', 'method': 'straight',
                                  'validFromMd': 0, 'validToMd': extent, 'azimuthAssumption': None,
                                  'extensionPolicy': 'error', 'sourceRefs': source_refs})
    for analyte in FEATURES:
        p['analytes'].append({'id': analyte, 'name': localized(analyte), 'unit': 'wt%',
                             'quantity': 'reported mass fraction; original column identity retained',
                             'sourceRefs': refs('56857404', 'header:' + analyte)})
    for hole, row in eligible:
        row_id = str(row['_row'])
        sid = 'rk-' + str(row['Sample_ID'])
        lineage = refs('56857404', row_id)
        p['supports'].append(support(sid, hole, number(row['From']), number(row['To']), lineage,
                                     'Original one-metre RC assay interval'))
        for analyte in FEATURES:
            p['determinations'].append(determination(f'{sid}:{analyte}', sid, analyte, number(row[analyte]),
                                                      row[analyte], 'wt%', lineage,
                                                      method='LOI-1000C' if analyte == 'LOI' else 'XRF',
                                                      lab='Kalassay'))
    issue(p, 'ALL_ANALYTE_ZERO', 'assay-source', zero,
          'Mapped source rows zero in every assay column are not treated as measured zero grades.',
          'Quarantined before modeling; original workbook retained by checksum.')
    issue(p, 'UNMATCHED_SOURCE_GEOMETRY', 'assay-source', unmatched,
          'These workbook rows have no unique acquired collar geometry.', 'No fabricated coordinates; excluded from spatial population.')
    issue(p, 'CONSTANT_SOURCE_COLUMNS', 'assay-source', ['Fe2o3', 'MnO', 'Na2O', 'LOI-100'],
          'Four source columns are identically zero on the eligible population.',
          'Excluded from canonical active analytes; no oxide conversion or missing-value claim.')
    issue(p, 'SOURCE_IRON_NOMENCLATURE', 'analytes', ['Fe'],
          'Workbook header is Fe, whereas the source paper describes FeO. Weight-percent values are preserved under the workbook name.',
          'No Fe-to-FeO conversion; source naming ambiguity remains visible.')
    issue(p, 'ASSUMED_TRAJECTORY', 'trajectories', [],
          'No measured station surveys accompany the acquired Rocklea files.', 'Vertical projection explicitly labeled.')
    return p
