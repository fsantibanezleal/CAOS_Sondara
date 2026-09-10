"""Source-specific project construction helpers; no numerical engine."""
from source_io import stable_hash


def refs(source, row):
    return [{'sourceId': source, 'rowId': str(row)}]


def localized(en, es=None):
    return {'en': en, 'es': es or en}


def project(identifier, name, sources, recipe, frame):
    return {'schema': 'drillhole.project/v1', 'id': identifier, 'name': name,
            'provenance': {'kind': 'field', 'sources': sources, 'recipe': recipe,
                           'recipeSha256': stable_hash({'recipe': recipe, 'sources': sources})},
            'frames': [frame], 'collars': [], 'surveys': [], 'trajectories': [],
            'analytes': [], 'supports': [], 'determinations': [], 'geology': [], 'issues': []}


def source(identifier, url, license_name, attribution, sha, format_name, encoding):
    return {'id': identifier, 'url': url, 'license': license_name, 'attribution': attribution,
            'sha256': sha, 'format': format_name, 'encoding': encoding}


def issue(p, code, table, rows, message, action, *, severity='warning', hole=None):
    p['issues'].append({'id': f"qa-{len(p['issues'])+1}", 'severity': severity,
                        'code': code, 'table': table, 'rowIds': [str(r) for r in rows],
                        'holeId': hole, 'message': message, 'action': action})


def support(identifier, hole, start, end, source_refs, description, *, unknown_weights=False):
    if start is None or end is None:
        kind, measure, at = 'unknown', 'unknown', None
    elif start == end:
        kind, measure, at = 'point', 'point', start
        start = end = None
    else:
        kind = 'sampling-envelope' if unknown_weights else 'interval'
        measure, at = ('unknown' if unknown_weights else 'uniform-length'), None
    return {'id': identifier, 'holeId': hole, 'kind': kind, 'fromMd': start, 'toMd': end,
            'atMd': at, 'samplingMeasure': measure, 'components': None,
            'sourceDescription': description, 'sourceRefs': source_refs}


def determination(identifier, support_id, analyte, value, raw, unit, source_refs,
                  *, qualifier=None, limit=None, method=None, lab=None):
    return {'id': identifier, 'supportId': support_id, 'analyteId': analyte, 'value': value,
            'rawValue': str(raw), 'qualifier': qualifier, 'detectionLimit': limit,
            'unit': unit, 'method': method, 'lab': lab, 'sourceRefs': source_refs}
