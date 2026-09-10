import pytest

from app.job_contract import JobRequest


def base(method="ok"):
    return {
        "schema": "sondara.job/v1", "projectHash": "0" * 64, "frameId": "local", "units": ["Cu"], "method": method,
        "observations": [{"id": "a", "group": "DH-01", "variable": 0, "value": 1.2, "support": {"id": "s", "kind": "point", "points": [(0., 0., 0.)], "weights": [1.]}}],
        "grid": {"origin": (0., 0., 0.), "spacing": (1., 1., 1.), "shape": (2, 2, 2)},
        "covariance": {"components": [{"family": "spherical", "ranges": (10., 10., 10.), "sill": [[1.]]}], "nugget": [[0.1]]},
    }


def test_strict_ordinary_kriging_request():
    request = JobRequest.model_validate(base())
    assert request.method == "ok"


def test_extra_fields_are_rejected():
    payload = base(); payload["unexpected"] = True
    with pytest.raises(ValueError): JobRequest.model_validate(payload)


def test_categorical_requires_training_image():
    payload = base("snesim"); payload["observations"] = []
    with pytest.raises(ValueError): JobRequest.model_validate(payload)
