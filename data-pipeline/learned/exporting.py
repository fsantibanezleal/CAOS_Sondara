"""Audited ONNX exports with parity on the held-out inputs; importing never executes a Python checkpoint.

The torch.export exporter (the default since PyTorch 2.9; the TorchScript one is marked for removal) writes each
node's Python stack trace, with local paths, into the node metadata: every metadata field is removed and every string
in the file is scanned before the file is accepted. Design: docs/design/features/learned-regression/design.md, section 5.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import time
import zipfile
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import torch
from learned.contracts import save_json

MAX_MODEL_BYTES = 8 * 1024 * 1024
MAX_NODES = 2000
OPSET = 18
FORBIDDEN_OPS = ("Loop", "Scan", "If", "SequenceMap")
FIXTURE_ROWS = 64
#: A path or a source location in any string of an exported model.
PATH_PATTERN = re.compile(r"([A-Za-z]:[\\/])|(/home/)|(/Users/)|(site-packages)|(File \")|(\.py\b)")
RAW_MARKERS = (b"site-packages", b"_Repos", b"File \"")


def digest(path: Path) -> dict:
    value = path.read_bytes()
    return {"sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}


def _strings(model: onnx.ModelProto):
    yield model.producer_name
    yield model.producer_version
    yield model.doc_string
    for p in model.metadata_props:
        yield p.key
        yield p.value
    graphs = [model.graph] + [f for f in model.functions]
    for g in graphs:
        yield getattr(g, "doc_string", "")
        for p in getattr(g, "metadata_props", []):
            yield p.key
            yield p.value
        for node in g.node:
            yield node.name
            yield node.doc_string
            for p in node.metadata_props:
                yield p.key
                yield p.value
    for v in list(model.graph.input) + list(model.graph.output) + list(model.graph.value_info):
        yield v.name
        yield v.doc_string
    for t in model.graph.initializer:
        yield t.name
        yield t.doc_string


def strip(model: onnx.ModelProto) -> onnx.ModelProto:
    """Remove every doc string and metadata field; the manifest beside the file is the documentation."""
    del model.metadata_props[:]
    model.doc_string = ""
    for g in [model.graph] + list(model.functions):
        if hasattr(g, "metadata_props"):
            del g.metadata_props[:]
        if hasattr(g, "doc_string"):
            g.doc_string = ""
        for node in g.node:
            node.doc_string = ""
            del node.metadata_props[:]
    for v in list(model.graph.input) + list(model.graph.output) + list(model.graph.value_info):
        v.doc_string = ""
        del v.metadata_props[:]
    for t in model.graph.initializer:
        t.doc_string = ""
        del t.metadata_props[:]
    return model


def scan_paths(path: Path) -> list[str]:
    """Every string of the model that looks like a path or a source location, and any raw path marker."""
    model = onnx.load(path, load_external_data=False)
    found = sorted({s for s in _strings(model) if s and PATH_PATTERN.search(s)})
    raw = path.read_bytes()
    found += [m.decode() for m in RAW_MARKERS if m in raw]
    return found


def audit_model(path: Path) -> dict:
    if path.stat().st_size > MAX_MODEL_BYTES:
        raise ValueError(f"{path.name}: {path.stat().st_size} bytes, over the {MAX_MODEL_BYTES} byte budget")
    model = onnx.load(path, load_external_data=False)
    if any(t.data_location == onnx.TensorProto.EXTERNAL for t in model.graph.initializer):
        raise ValueError("external ONNX data is not an accepted model")
    if model.functions:
        raise ValueError("local ONNX functions are not accepted")
    if any(node.domain not in ("", "ai.onnx") for node in model.graph.node):
        raise ValueError("custom ONNX operators are not accepted")
    if any(node.op_type in FORBIDDEN_OPS for node in model.graph.node):
        raise ValueError("control-flow ONNX graphs are not accepted")
    if len(model.graph.node) > MAX_NODES:
        raise ValueError(f"{len(model.graph.node)} nodes, over the {MAX_NODES} node budget")
    leaks = scan_paths(path)
    if leaks:
        raise ValueError(f"the model carries paths or source locations: {leaks[:3]}")
    onnx.checker.check_model(model, full_check=True)
    return digest(path) | {"operators": sorted({n.op_type for n in model.graph.node}),
                           "nodes": len(model.graph.node),
                           "opset": [[o.domain, o.version] for o in model.opset_import]}


def _run_torch(model, inputs, device, batch=4096) -> list[np.ndarray]:
    """Every output of ``model`` on ``inputs``, batched, as float64 arrays (a single output is a list of one)."""
    model = model.to(device).eval()
    parts = []
    with torch.no_grad():
        for s in range(0, len(inputs[0]), batch):
            out = model(*(torch.as_tensor(x[s:s + batch], dtype=torch.float32, device=device) for x in inputs))
            parts.append([o.cpu() for o in (out if isinstance(out, tuple) else (out,))])
    model.cpu()
    return [torch.cat([p[k] for p in parts]).numpy().astype(np.float64) for k in range(len(parts[0]))]


def export_model(model: torch.nn.Module, inputs: tuple[np.ndarray, ...], names: list[str], destination: Path,
                 metadata: dict, *, tolerance: float, outputs: dict | None = None) -> dict:
    """Export ``model`` to ``destination/model.onnx`` and check it on every row of ``inputs`` (the held-out inputs).

    ``outputs`` names each output with its unit (default: one output, ``value``, in native units). ONNX Runtime on
    the CPU and, when present, PyTorch on CUDA must agree with PyTorch on the CPU within ``tolerance`` on every output;
    the record and a fixture of the first rows go to ``parity.json``.
    """
    outputs = outputs or {"value": "native"}
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / "model.onnx"
    inputs = tuple(np.asarray(x, dtype=np.float32) for x in inputs)
    model = model.cpu().eval()
    sample_rows = max(2, min(FIXTURE_ROWS, len(inputs[0])))
    sample = tuple(torch.as_tensor(np.resize(x, (sample_rows,) + x.shape[1:])) for x in inputs)
    batch = torch.export.Dim("batch")
    log = io.StringIO()
    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        torch.onnx.export(model, sample, path, input_names=names, output_names=list(outputs), opset_version=OPSET,
                          dynamo=True, external_data=False, dynamic_shapes=tuple({0: batch} for _ in names))
    onnx.save(strip(onnx.load(path)), path)
    audit = audit_model(path)
    expected = _run_torch(model, inputs, "cpu")
    session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    started = time.perf_counter()
    runs = [session.run(None, dict(zip(names, (x[s:s + 4096] for x in inputs), strict=True)))
            for s in range(0, len(inputs[0]), 4096)]
    actual = [np.concatenate([r[k] for r in runs]).astype(np.float64) for k in range(len(outputs))]
    seconds = time.perf_counter() - started

    def worst(got):
        return max((float(np.max(np.abs(g - e))) for g, e in zip(got, expected, strict=True) if e.size), default=0.0)

    onnx_error = worst(actual)
    cuda_error = worst(_run_torch(model, inputs, "cuda")) if torch.cuda.is_available() else None
    parity = {"schema": "sondara.onnx-parity/v1", "rows": len(expected[0]), "tolerance": tolerance,
              "unit": ", ".join(f"{n}: {u}" for n, u in outputs.items()) if len(outputs) > 1 else outputs["value"],
              "onnxCpuMaxAbsolute": onnx_error, "torchCudaMaxAbsolute": cuda_error,
              "passed": onnx_error <= tolerance and (cuda_error is None or cuda_error <= tolerance),
              "onnxSeconds": round(seconds, 4), "onnxRuntime": ort.__version__, "torch": torch.__version__,
              "fixture": {"inputs": {n: {"shape": [min(FIXTURE_ROWS, len(x))] + list(x.shape[1:]),
                                         "data": x[:FIXTURE_ROWS].reshape(-1).tolist()}
                                     for n, x in zip(names, inputs, strict=True)},
                          "outputs": {n: e[:FIXTURE_ROWS].tolist() for n, e in zip(outputs, expected, strict=True)}}}
    save_json(destination / "parity.json", parity)
    if not parity["passed"]:
        raise ArithmeticError(f"{destination}: parity outside {tolerance:g} (ONNX {onnx_error:.3g}, CUDA {cuda_error})")
    manifest = metadata | {"schema": "sondara.learned-model/v1", "model": audit, "inputs": {
        n: {"shape": ["batch"] + list(x.shape[1:]), "dtype": "float32"} for n, x in zip(names, inputs, strict=True)},
        "outputs": {n: {"shape": ["batch"] + list(e.shape[1:]), "dtype": "float32", "unit": u}
                    for (n, u), e in zip(outputs.items(), expected, strict=True)},
        "parity": digest(destination / "parity.json") | {k: parity[k] for k in (
            "rows", "tolerance", "onnxCpuMaxAbsolute", "torchCudaMaxAbsolute")},
        "exporter": {"torch": torch.__version__, "onnx": onnx.__version__, "opset": OPSET, "path": "torch.export"},
        "importPolicy": "standard ONNX bound to its project; no Python pickle"}
    save_json(destination / "manifest.json", manifest)
    with zipfile.ZipFile(destination / "portable-model.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in ("manifest.json", "model.onnx", "parity.json"):
            info = zipfile.ZipInfo(file, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, (destination / file).read_bytes())
    return manifest


def validate_portable(path: Path) -> dict:
    """Structural preflight of a portable model; the caller still checks its binding to the project."""
    with zipfile.ZipFile(path) as archive:
        expected = {"manifest.json", "model.onnx", "parity.json"}
        if len(archive.infolist()) != 3 or set(archive.namelist()) != expected:
            raise ValueError("a portable model holds exactly manifest.json, model.onnx and parity.json")
        if any(i.file_size > MAX_MODEL_BYTES for i in archive.infolist()):
            raise ValueError("a portable model file is over the byte budget")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("schema") != "sondara.learned-model/v1":
            raise ValueError("unsupported portable model schema")
        raw = archive.read("model.onnx")
        if len(raw) != manifest["model"]["bytes"] or hashlib.sha256(raw).hexdigest() != manifest["model"]["sha256"]:
            raise ValueError("model hash mismatch")
        graph = onnx.load_model_from_string(raw)
        if any(t.data_location == onnx.TensorProto.EXTERNAL for t in graph.graph.initializer) or graph.functions:
            raise ValueError("external tensors and local functions are not accepted")
        if any(n.domain not in ("", "ai.onnx") or n.op_type in FORBIDDEN_OPS for n in graph.graph.node):
            raise ValueError("unsupported model graph")
        if len(graph.graph.node) > MAX_NODES:
            raise ValueError("graph budget exceeded")
        onnx.checker.check_model(graph, full_check=True)
        return manifest
