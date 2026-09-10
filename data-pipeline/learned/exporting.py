"""Audited ONNX bundles; user import never executes Python checkpoint objects."""

from __future__ import annotations

import hashlib
import json
import time
import zipfile
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import torch
from learned.contracts import save_json

MAX_MODEL_BYTES = 8 * 1024 * 1024


def digest(path: Path) -> dict:
    value = path.read_bytes()
    return {"sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}


def audit_model(path: Path) -> dict:
    if path.stat().st_size > MAX_MODEL_BYTES:
        raise ValueError("ONNX byte budget exceeded")
    model = onnx.load(path, load_external_data=False)
    if any(t.data_location == onnx.TensorProto.EXTERNAL for t in model.graph.initializer):
        raise ValueError("external ONNX data is not an accepted model import")
    if any(node.domain not in ("", "ai.onnx") for node in model.graph.node):
        raise ValueError("custom ONNX operations are not accepted")
    if any(node.op_type in ("Loop", "Scan", "If", "SequenceMap") for node in model.graph.node):
        raise ValueError("dynamic control-flow models are not accepted")
    if len(model.graph.node) > 2000:
        raise ValueError("ONNX graph budget exceeded")
    onnx.checker.check_model(model, full_check=True)
    return digest(path) | {"operators": sorted({n.op_type for n in model.graph.node}),
                           "nodes": len(model.graph.node), "opset": [(o.domain, o.version) for o in model.opset_import]}


def export_model(model: torch.nn.Module, inputs: tuple[np.ndarray, ...], names: list[str],
                 outputs: list[str], destination: Path, metadata: dict, *,
                 absolute_tolerance: float, relative_tolerance: float = 2e-5) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / "model.onnx"
    cpu_model = model.cpu().eval()
    cpu_inputs = tuple(torch.tensor(value, dtype=torch.float32) for value in inputs)
    with torch.no_grad():
        cpu_result = cpu_model(*cpu_inputs)
    expected = cpu_result if isinstance(cpu_result, tuple) else (cpu_result,)
    expected = [value.numpy() for value in expected]
    torch.onnx.export(cpu_model, cpu_inputs, path, input_names=names, output_names=outputs,
                      dynamic_axes={name: {0: "batch"} for name in names + outputs},
                      opset_version=18, dynamo=False, external_data=False)
    graph = onnx.load(path)
    graph.doc_string = "Sondara independently implemented scientific model; see adjacent manifest."
    graph.graph.doc_string = ""
    for node in graph.graph.node:
        node.doc_string = ""
        del node.metadata_props[:]
    del graph.metadata_props[:]
    onnx.save(graph, path)
    audit = audit_model(path)
    session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    feeds = dict(zip(names, [x.astype(np.float32) for x in inputs], strict=True))
    started = time.perf_counter()
    actual = session.run(None, feeds)
    seconds = time.perf_counter() - started
    onnx_errors = []
    for a, b in zip(expected, actual, strict=True):
        np.testing.assert_allclose(a, b, atol=absolute_tolerance, rtol=relative_tolerance)
        onnx_errors.append(float(np.max(np.abs(a - b))))
    cuda_errors = None
    if torch.cuda.is_available():
        with torch.no_grad():
            cuda_result = cpu_model.cuda()(*(value.cuda() for value in cpu_inputs))
        cuda_outputs = cuda_result if isinstance(cuda_result, tuple) else (cuda_result,)
        cuda_errors = []
        for a, b in zip(expected, cuda_outputs, strict=True):
            array = b.cpu().numpy()
            np.testing.assert_allclose(a, array, atol=absolute_tolerance, rtol=relative_tolerance)
            cuda_errors.append(float(np.max(np.abs(a - array))))
        cpu_model.cpu()
    fixtures = {"schema": "sondara.onnx-parity.v1", "inputs": {
        name: {"shape": list(value.shape), "data": value.astype(np.float32).reshape(-1).tolist()}
        for name, value in feeds.items()}, "outputs": {
        name: {"shape": list(value.shape), "data": value.reshape(-1).tolist()}
        for name, value in zip(outputs, expected, strict=True)},
        "absoluteTolerance": absolute_tolerance, "relativeTolerance": relative_tolerance,
        "onnxCpuMaxAbsolute": onnx_errors, "torchCudaMaxAbsolute": cuda_errors,
        "onnxInferenceSeconds": seconds}
    save_json(destination / "parity.json", fixtures)
    manifest = metadata | {"schema": "sondara.learned-model.v1", "model": audit,
                           "inputs": names, "outputs": outputs, "dtype": "float32",
                           "maximumBatch": 4096, "parity": digest(destination / "parity.json"),
                           "importPolicy": "source-bound standard ONNX only; no Python pickle"}
    save_json(destination / "manifest.json", manifest)
    with zipfile.ZipFile(destination / "portable-model.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in ("manifest.json", "model.onnx", "parity.json"):
            info = zipfile.ZipInfo(file, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, (destination / file).read_bytes())
    return manifest


def validate_portable(path: Path) -> dict:
    """Structural preflight used by local tooling; callers still check project binding."""
    with zipfile.ZipFile(path) as archive:
        expected = {"manifest.json", "model.onnx", "parity.json"}
        if len(archive.infolist()) != 3 or set(archive.namelist()) != expected:
            raise ValueError("portable model must contain exactly the three known files")
        if any(i.file_size > MAX_MODEL_BYTES for i in archive.infolist()):
            raise ValueError("portable model expanded byte budget exceeded")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("schema") != "sondara.learned-model.v1":
            raise ValueError("unsupported portable model schema")
        raw = archive.read("model.onnx")
        if len(raw) != manifest["model"]["bytes"] or hashlib.sha256(raw).hexdigest() != manifest["model"]["sha256"]:
            raise ValueError("model hash mismatch")
        graph = onnx.load_model_from_string(raw)
        if any(t.data_location == onnx.TensorProto.EXTERNAL for t in graph.graph.initializer):
            raise ValueError("external model tensors are forbidden")
        if any(n.domain not in ("", "ai.onnx") or n.op_type in ("Loop", "Scan", "If", "SequenceMap")
               for n in graph.graph.node):
            raise ValueError("unsupported model graph")
        if len(graph.graph.node) > 2000:
            raise ValueError("graph budget exceeded")
        onnx.checker.check_model(graph, full_check=True)
        return manifest
