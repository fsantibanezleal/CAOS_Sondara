"""Reproducible, resumable real-data fitting with sealed validation selection."""

from __future__ import annotations

import copy
import random
import time
from pathlib import Path

import numpy as np
import torch
from learned.contracts import canonical_hash, save_json
from torch import nn


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.set_num_threads(2)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False


def tensor_inputs(values: tuple[np.ndarray, ...], device: str) -> tuple[torch.Tensor, ...]:
    return tuple(torch.as_tensor(v, dtype=torch.float32, device=device) for v in values)


def predict(model: nn.Module, inputs: tuple[torch.Tensor, ...], batch: int = 1024) -> torch.Tensor:
    model.eval()
    with torch.no_grad():
        return torch.cat([model(*(v[start:start + batch] for v in inputs))
                          for start in range(0, len(inputs[0]), batch)])


def fit(model: nn.Module, train: tuple[np.ndarray, ...], train_y: np.ndarray,
        validation: tuple[np.ndarray, ...], validation_y: np.ndarray,
        validation_holes: np.ndarray, output: Path, recipe: dict, seed: int,
        device: str, *, epochs: int = 400, patience: int = 40,
        native_scale: float = 1, reconstruction: bool = False) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    recipe_hash = canonical_hash(recipe | {"seed": seed, "epochs": epochs, "patience": patience})
    completed = output / "fit.json"
    if completed.exists():
        import json
        result = json.loads(completed.read_text(encoding="utf-8"))
        if result["recipeHash"] != recipe_hash:
            raise ValueError("completed fit has another recipe; choose a new run directory")
        model.load_state_dict(torch.load(output / "weights.pt", weights_only=True, map_location="cpu"))
        return result
    seed_everything(seed)
    # Reset the already constructed layers after setting the seed.
    for module in model.modules():
        if hasattr(module, "reset_parameters"):
            module.reset_parameters()
    model.to(device)
    inputs = tensor_inputs(train, device)
    targets = torch.as_tensor(train_y, dtype=torch.float32, device=device)
    valid_inputs = tensor_inputs(validation, device)
    valid_targets = torch.as_tensor(validation_y, dtype=torch.float32, device=device)
    groups = [torch.as_tensor(np.flatnonzero(validation_holes == hole), device=device)
              for hole in np.unique(validation_holes)]
    optimizer = torch.optim.AdamW(model.parameters(), lr=.001, weight_decay=.0001)
    best, best_epoch, stale, history, start_epoch = float("inf"), 0, 0, [], 0
    best_state = copy.deepcopy(model.state_dict())
    resume_file = output / "resume.pt"
    if resume_file.exists():
        state = torch.load(resume_file, weights_only=True, map_location=device)
        if state["recipeHash"] != recipe_hash:
            raise ValueError("resume recipe mismatch")
        model.load_state_dict(state["model"])
        optimizer.load_state_dict(state["optimizer"])
        best, best_epoch, stale, history = state["best"], state["bestEpoch"], state["stale"], state["history"]
        best_state, start_epoch = state["bestState"], state["epoch"]
        torch.set_rng_state(state["cpuRng"].cpu())
        if device.startswith("cuda"):
            torch.cuda.set_rng_state(state["cudaRng"].cpu())
    started = time.perf_counter()
    if device.startswith("cuda"):
        torch.cuda.reset_peak_memory_stats()
    for epoch in range(start_epoch, epochs):
        model.train()
        permutation = torch.randperm(len(targets), device=device)
        losses = []
        for start in range(0, len(targets), 128):
            batch = permutation[start:start + 128]
            optimizer.zero_grad(set_to_none=True)
            prediction = model(*(v[batch] for v in inputs))
            loss = torch.mean((prediction - targets[batch]) ** 2)
            if not torch.isfinite(loss):
                raise ArithmeticError("non-finite training objective")
            loss.backward()
            optimizer.step()
            losses.append(loss.detach() * len(batch))
        prediction = predict(model, valid_inputs)
        squared = (prediction - valid_targets) ** 2
        if reconstruction:
            score = float(squared.mean().cpu())
        else:
            score = float(torch.stack([squared[index].mean().sqrt() for index in groups]).mean().cpu()) * native_scale
        history.append({"epoch": epoch + 1, "trainMse": float(torch.stack(losses).sum().cpu()) / len(targets),
                        "validationObjective": score})
        if score < best:
            best, best_epoch, stale = score, epoch + 1, 0
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
        else:
            stale += 1
        if (epoch + 1) % 20 == 0 or stale >= patience or epoch + 1 == epochs:
            torch.save({"recipeHash": recipe_hash, "model": model.state_dict(),
                        "optimizer": optimizer.state_dict(), "bestState": best_state,
                        "best": best, "bestEpoch": best_epoch, "stale": stale,
                        "epoch": epoch + 1, "history": history, "cpuRng": torch.get_rng_state(),
                        "cudaRng": torch.cuda.get_rng_state() if device.startswith("cuda") else torch.get_rng_state()}, resume_file)
        if stale >= patience:
            break
    if device.startswith("cuda"):
        torch.cuda.synchronize()
    duration = time.perf_counter() - started
    model.load_state_dict(best_state)
    torch.save(best_state, output / "weights.pt")
    result = {"schema": "sondara.learned-fit.v1", "recipeHash": recipe_hash, "recipe": recipe,
              "seed": seed, "bestEpoch": best_epoch, "epochsExecuted": len(history),
              "bestValidationObjective": best, "selection": "validation reconstruction MSE" if reconstruction
              else "validation whole-hole macro native-unit RMSE", "history": history,
              "fitSecondsThisInvocation": duration, "device": device,
              "deviceName": torch.cuda.get_device_name() if device.startswith("cuda") else "CPU",
              "peakAllocatedBytes": torch.cuda.max_memory_allocated() if device.startswith("cuda") else None,
              "torch": torch.__version__, "cudaRuntime": torch.version.cuda,
              "trainRows": len(train_y), "validationRows": len(validation_y),
              "optimizer": {"name": "AdamW", "learningRate": .001, "weightDecay": .0001, "batch": 128}}
    save_json(completed, result)
    # Resume remains an ignored local checkpoint; published weights are restricted-load tensors only.
    return result
