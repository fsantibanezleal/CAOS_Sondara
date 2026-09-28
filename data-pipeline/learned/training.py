"""Reproducible, resumable fits with validation selection and restricted-load weights.

One fit is one configuration and one seed. The model returns native units; the loss is the mean squared error over
the squared training scale, and the validation objective is the hole-macro RMSE in native units (the mean over
validation holes of each hole's RMSE). The best epoch's weights are kept. Design:
docs/design/features/learned-regression/design.md, section 2.
"""

from __future__ import annotations

import copy
import json
import random
import time
from pathlib import Path

import numpy as np
import torch
from learned.contracts import canonical_hash, save_json
from torch import nn

OPTIMIZER = {"name": "AdamW", "learningRate": 0.001, "weightDecay": 0.0001, "batch": 128}
EPOCHS, PATIENCE, RESUME_EVERY = 400, 40, 20


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False


def tensors(values: tuple[np.ndarray, ...], device: str) -> tuple[torch.Tensor, ...]:
    return tuple(torch.as_tensor(np.asarray(v), dtype=torch.float32, device=device) for v in values)


def predict(model: nn.Module, inputs: tuple[torch.Tensor, ...], batch: int = 1024) -> torch.Tensor:
    model.eval()
    with torch.no_grad():
        return torch.cat([model(*(v[start:start + batch] for v in inputs))
                          for start in range(0, len(inputs[0]), batch)])


def hole_macro_rmse(prediction: np.ndarray, truth: np.ndarray, holes: np.ndarray) -> float:
    error = np.asarray(prediction, dtype=np.float64) - np.asarray(truth, dtype=np.float64)
    return float(np.mean([np.sqrt(np.mean(error[holes == h] ** 2)) for h in np.unique(holes)]))


def weights_sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def fit(model: nn.Module, train: tuple[np.ndarray, ...], train_y: np.ndarray, validation: tuple[np.ndarray, ...],
        validation_y: np.ndarray, validation_holes: np.ndarray, output: Path, recipe: dict, seed: int, device: str,
        *, scale: float, epochs: int = EPOCHS, patience: int = PATIENCE) -> dict:
    """Fit ``model`` in place; reuse a finished fit with the same recipe hash, refuse one with another."""
    output.mkdir(parents=True, exist_ok=True)
    recipe_hash = canonical_hash({**recipe, "seed": seed, "epochs": epochs, "patience": patience,
                                  "optimizer": OPTIMIZER})
    completed = output / "fit.json"
    if completed.exists():
        result = json.loads(completed.read_text(encoding="utf-8"))
        if result["recipeHash"] != recipe_hash:
            raise ValueError(f"{output}: a finished fit with another recipe is there; remove it to refit")
        weights = output / "weights.pt"
        if weights_sha256(weights) != result["weightsSha256"]:
            raise ValueError(f"{weights}: the weights do not match their fit record")
        model.load_state_dict(torch.load(weights, weights_only=True, map_location="cpu"))
        return {**result, "reused": True}
    seed_everything(seed)
    for module in model.modules():  # the layers were built before the seed: initialize them from it
        if hasattr(module, "reset_parameters"):
            module.reset_parameters()
    model.to(device)
    inputs, valid_inputs = tensors(train, device), tensors(validation, device)
    targets = torch.as_tensor(train_y, dtype=torch.float32, device=device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=OPTIMIZER["learningRate"],
                                  weight_decay=OPTIMIZER["weightDecay"])
    best, best_epoch, stale, history, start_epoch = float("inf"), 0, 0, [], 0
    best_state = copy.deepcopy(model.state_dict())
    resume_file = output / "resume.pt"
    if resume_file.exists():
        state = torch.load(resume_file, weights_only=True, map_location=device)
        if state["recipeHash"] != recipe_hash:
            raise ValueError(f"{resume_file}: an interrupted fit with another recipe; remove it to refit")
        model.load_state_dict(state["model"])
        optimizer.load_state_dict(state["optimizer"])
        best, best_epoch, stale, start_epoch = state["best"], state["bestEpoch"], state["stale"], state["epoch"]
        history = json.loads(state["history"])
        best_state = state["bestState"]
        torch.set_rng_state(state["cpuRng"].cpu())
        if device.startswith("cuda"):
            torch.cuda.set_rng_state(state["cudaRng"].cpu())
    started = time.perf_counter()
    if device.startswith("cuda"):
        torch.cuda.reset_peak_memory_stats()
    n = len(targets)
    for epoch in range(start_epoch, epochs):
        model.train()
        permutation = torch.randperm(n, device=device)
        total = torch.zeros((), device=device)
        for start in range(0, n, OPTIMIZER["batch"]):
            batch = permutation[start:start + OPTIMIZER["batch"]]
            optimizer.zero_grad(set_to_none=True)
            loss = torch.mean(((model(*(v[batch] for v in inputs)) - targets[batch]) / scale) ** 2)
            if not torch.isfinite(loss):
                raise ArithmeticError(f"{output}: non-finite training loss at epoch {epoch + 1}")
            loss.backward()
            optimizer.step()
            total += loss.detach() * len(batch)
        score = hole_macro_rmse(predict(model, valid_inputs).cpu().numpy(), validation_y, validation_holes)
        history.append({"epoch": epoch + 1, "trainLoss": float(total.cpu()) / n, "validationObjective": score})
        if score < best:
            best, best_epoch, stale = score, epoch + 1, 0
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
        else:
            stale += 1
        if (epoch + 1) % RESUME_EVERY == 0:
            torch.save({"recipeHash": recipe_hash, "model": model.state_dict(), "optimizer": optimizer.state_dict(),
                        "bestState": best_state, "best": best, "bestEpoch": best_epoch, "stale": stale,
                        "epoch": epoch + 1, "history": json.dumps(history), "cpuRng": torch.get_rng_state(),
                        "cudaRng": torch.cuda.get_rng_state() if device.startswith("cuda") else torch.get_rng_state()},
                       resume_file)
        if stale >= patience:
            break
    if device.startswith("cuda"):
        torch.cuda.synchronize()
    seconds = time.perf_counter() - started
    model.load_state_dict(best_state)
    model.cpu()
    weights = output / "weights.pt"
    torch.save(best_state, weights)
    result = {"schema": "sondara.learned-fit/v1", "recipeHash": recipe_hash, "recipe": recipe, "seed": seed,
              "bestEpoch": best_epoch, "epochsRun": len(history), "bestValidationObjective": best,
              "objective": "validation hole-macro RMSE, native units", "history": history,
              "fitSeconds": round(seconds, 3), "device": device,
              "deviceName": torch.cuda.get_device_name() if device.startswith("cuda") else "CPU",
              "cpuThreads": torch.get_num_threads(),
              "peakAllocatedBytes": torch.cuda.max_memory_allocated() if device.startswith("cuda") else None,
              "torch": torch.__version__, "cudaRuntime": torch.version.cuda, "trainRows": int(n),
              "validationRows": len(validation_y), "optimizer": OPTIMIZER, "epochs": epochs, "patience": patience,
              "weightsSha256": weights_sha256(weights)}
    save_json(completed, result)
    resume_file.unlink(missing_ok=True)
    return {**result, "reused": False}
