"""Constructors for the canonical project tables (`drillhole.project/v2`, schemas/project.schema.json); no numerics."""
from source_io import stable_hash

SCHEMA = 'drillhole.project/v2'
STATES = ('measured', 'censored-below', 'censored-above', 'missing', 'not-sampled', 'lost-core', 'sentinel')
QUALIFIER = {'measured': '=', 'censored-below': '<', 'censored-above': '>'}


def refs(source, row):
    return [{'sourceId': source, 'rowId': str(row)}]


def localized(en, es=None):
    return {'en': en, 'es': es or en}


def frame(identifier, kind, *, horizontal_crs=None, horizontal_definition=None, vertical_datum=None, origin=None,
          assumptions=()):
    return {'id': identifier, 'kind': kind, 'unit': 'm', 'horizontalCrs': horizontal_crs,
            'horizontalDefinition': horizontal_definition, 'verticalDatum': vertical_datum, 'origin': origin,
            'assumptions': list(assumptions)}


def project(identifier, name, sources, recipe, frame_record, *, kind='field'):
    return {'schema': SCHEMA, 'id': identifier, 'name': name,
            'provenance': {'kind': kind, 'sources': sources, 'recipe': recipe,
                           'recipeSha256': stable_hash({'recipe': recipe, 'sources': sources})},
            'frames': [frame_record], 'collars': [], 'surveys': [], 'trajectories': [],
            'analytes': [], 'supports': [], 'determinations': [], 'geology': [], 'qc': [], 'exclusions': [],
            'issues': [], 'waterfall': []}


def source(identifier, url, license_name, attribution, sha, format_name, encoding):
    return {'id': identifier, 'url': url, 'license': license_name, 'attribution': attribution,
            'sha256': sha, 'format': format_name, 'encoding': encoding}


def collar(identifier, namespace, source_hole, frame_id, x, y, z, source_refs, *, total_depth=None,
           observed_depth=None, orientation=None):
    return {'id': identifier, 'sourceHoleId': source_hole, 'namespace': namespace, 'frameId': frame_id,
            'x': x, 'y': y, 'z': z, 'totalDepth': total_depth, 'observedDepthMax': observed_depth,
            'orientation': orientation, 'sourceRefs': source_refs}


def orientation(azimuth, dip, reference, source_inclination=None):
    return {'azimuth': azimuth, 'dip': dip, 'azimuthReference': reference, 'sourceInclination': source_inclination}


def survey(identifier, hole, md, azimuth, dip, role, source_refs, *, reference='unknown', instrument=None):
    return {'id': identifier, 'holeId': hole, 'md': md, 'azimuth': azimuth, 'dip': dip, 'azimuthReference': reference,
            'role': role, 'instrument': instrument, 'sourceRefs': source_refs}


def trajectory(hole, kind, source_refs, *, valid_to=None, azimuth_assumption=None, start='none', end='tangent'):
    return {'holeId': hole, 'kind': kind,
            'method': 'minimum-curvature' if kind == 'measured-stations' else 'straight',
            'validFromMd': 0.0, 'validToMd': valid_to, 'azimuthAssumption': azimuth_assumption,
            'startExtension': start, 'endExtension': end, 'sourceRefs': source_refs}


def issue(p, code, table, rows, message, action, *, severity='warning', hole=None):
    p['issues'].append({'id': f"qa-{len(p['issues'])+1}", 'severity': severity,
                        'code': code, 'table': table, 'rowIds': [str(r) for r in rows],
                        'holeId': hole, 'message': message, 'action': action})


def support(identifier, hole, start, end, source_refs, description, *, sample=None, unknown_weights=False):
    if start is None or end is None:
        kind, measure, at = 'unknown', 'unknown', None
    elif start == end:
        kind, measure, at = 'point', 'point', start
        start = end = None
    else:
        kind = 'sampling-envelope' if unknown_weights else 'interval'
        measure, at = ('unknown' if unknown_weights else 'uniform-length'), None
    return {'id': identifier, 'holeId': hole, 'sampleId': sample, 'kind': kind, 'fromMd': start, 'toMd': end,
            'atMd': at, 'samplingMeasure': measure, 'components': None,
            'sourceDescription': description, 'sourceRefs': source_refs}


def determination(identifier, support_id, analyte, value, raw, unit, source_refs, *, state='measured',
                  limit=None, method=None, lab=None, sample_role='original'):
    if state not in STATES:
        raise ValueError(f'unknown determination state {state!r}')
    return {'id': identifier, 'supportId': support_id, 'analyteId': analyte,
            'value': value if state == 'measured' else None, 'rawValue': str(raw),
            'qualifier': QUALIFIER.get(state), 'state': state, 'detectionLimit': limit,
            'unit': unit, 'method': method, 'lab': lab, 'sampleRole': sample_role, 'sourceRefs': source_refs}
