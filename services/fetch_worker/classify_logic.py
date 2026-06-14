"""Comment 3-class classifier inference on the worker (GPU).

Loads the fine-tuned klue/roberta-large **3-class** checkpoint from
`CLASSIFY_MODEL_DIR` once on first call and serves batched classification
(PRODUCT_OPINION / VIDEO_REACTION / QUESTION).

Mirrors `scope_logic.py` (same lazy-load + `_MODEL_LOCK` + bf16-on-cuda
pattern). Unlike scope, comment classification tokenizes the **raw comment
text** directly with no `build_input_text` preprocessing — matching the
reference `local_classifier.classifier._predict` (softmax argmax). So this
module has no dependency on `comment_filtering_agent` or any train-side repo.

The checkpoint is the same artifact the reference benchmark uses, e.g.
`.../testLocalvsAPI/local_classifier/artifacts/3_labels/klue__roberta-large/model/best`.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from threading import Lock
from typing import Iterable

# Heavy deps (torch/transformers) imported lazily inside _ensure_loaded — keeps
# import-time cheap and lets unit tests stub the module without pulling torch.
_MODEL_LOCK = Lock()
_MODEL_STATE: dict = {}

MODEL_VERSION = "klue-roberta-large-comment-3class-v1"
MAX_LENGTH = 128  # matches local_classifier.config.MAX_SEQ_LEN
DEFAULT_BATCH_SIZE = 32

# id2label — MUST match training label order (local_classifier/config.py
# LABEL_NAMES). The 3-class scheme absorbs legacy NOISE/CHATTER/OFF_TOPIC into
# VIDEO_REACTION, so only these three are ever emitted.
ID2LABEL = {0: "PRODUCT_OPINION", 1: "VIDEO_REACTION", 2: "QUESTION"}


@dataclass
class ClassifyResult:
    label: str
    confidence: float
    latency_ms: int


def _ensure_loaded() -> None:
    if _MODEL_STATE.get("ready"):
        return
    with _MODEL_LOCK:
        if _MODEL_STATE.get("ready"):
            return
        import torch  # type: ignore
        from transformers import (  # type: ignore
            AutoModelForSequenceClassification,
            AutoTokenizer,
        )

        model_dir = os.environ.get("CLASSIFY_MODEL_DIR")
        if not model_dir:
            raise RuntimeError("CLASSIFY_MODEL_DIR not configured on worker")
        if not os.path.isdir(model_dir):
            raise RuntimeError(f"CLASSIFY_MODEL_DIR does not exist: {model_dir}")

        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.bfloat16 if device == "cuda" else torch.float32

        tokenizer = AutoTokenizer.from_pretrained(model_dir)
        model = AutoModelForSequenceClassification.from_pretrained(
            model_dir, torch_dtype=dtype
        ).to(device).eval()

        _MODEL_STATE.update(
            tokenizer=tokenizer,
            model=model,
            device=device,
            torch=torch,
            ready=True,
        )
        print(
            f"[CLASSIFY] Loaded {MODEL_VERSION} from {model_dir} on {device} (dtype={dtype})",
            flush=True,
        )


def classify_batch(comments: Iterable[str]) -> list[ClassifyResult]:
    """Classify each comment string into one of the 3 classes.

    comments: iterable of raw comment strings.
    Returns list aligned to input order. Each item gets its own latency_ms
    measured from the batch slice it belonged to.
    """
    comments_list = [str(c) for c in comments]
    if not comments_list:
        return []

    _ensure_loaded()
    torch = _MODEL_STATE["torch"]
    tokenizer = _MODEL_STATE["tokenizer"]
    model = _MODEL_STATE["model"]
    device = _MODEL_STATE["device"]

    results: list[ClassifyResult] = []
    batch_size = int(os.environ.get("CLASSIFY_BATCH_SIZE", DEFAULT_BATCH_SIZE))

    for start in range(0, len(comments_list), batch_size):
        slice_ = comments_list[start : start + batch_size]
        t0 = time.perf_counter()
        enc = tokenizer(
            slice_,
            padding=True,
            truncation=True,
            max_length=MAX_LENGTH,
            return_tensors="pt",
        ).to(device)
        with torch.no_grad():
            logits = model(**enc).logits.float()
            probs = torch.softmax(logits, dim=-1).cpu().numpy()
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        per_item_ms = max(1, elapsed_ms // len(slice_))

        for prob in probs:
            label_id = int(prob.argmax())
            confidence = float(prob[label_id])
            results.append(
                ClassifyResult(
                    label=ID2LABEL.get(label_id, "VIDEO_REACTION"),
                    confidence=confidence,
                    latency_ms=per_item_ms,
                )
            )

    return results
