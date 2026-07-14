"""Post-hoc relabel of a COMPLETED run: map a temperature-unsupported model's
mislabeled ``temperature: 0.0`` results to the native/None sentinel.

A run produced by an older ``arms.py`` recorded ``decode.temperature`` (0.0) for models
that reject a caller-set temperature (e.g. Opus 4.8), even though the provider call
omitted the parameter. That misreports the headline condition (Opus has NO determinism
knob) as "temperature 0". This helper rewrites ``fig4_data.json`` (and ``arm_a_raw.jsonl``,
so the raw evidence stays consistent) so an already-finished ~3h run does NOT need to be
re-run.

Safety:
  * refuses an in-progress / absent run (requires ``fig4_data.json`` present);
  * backs up each file it touches to ``<name>.pre-relabel.bak`` before rewriting;
  * targets are inferred from the manifest (``supports_temperature=False``) unless
    ``--labels`` is given -- so it only ever nulls the models that truly have no knob.

    uv run python -m studies.tier3_determinism.relabel_native_temp runs/<stamp>
    uv run python -m studies.tier3_determinism.relabel_native_temp runs/<stamp> --labels opus-4.8
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def _native_labels_from_manifest(run_dir: Path) -> list[str]:
    """Model labels the manifest marks as ``supports_temperature=False`` (no temp knob)."""
    manifest = json.loads((run_dir / "manifest.json").read_text())
    return [m["label"] for m in manifest.get("models", []) if not m.get("supports_temperature", True)]


def _backup(path: Path) -> Path:
    """Snapshot the PRISTINE original exactly once, and never destroy it.

    A ``.pre-relabel.bak`` is created only if it does not already exist -- so the FIRST
    relabel captures the untouched original, and any later relabel (e.g. a second call for
    a different label) leaves that original backup intact instead of renaming an
    already-modified artifact onto it. We copy (not rename), so ``path`` stays in place
    and the backup persists across any number of relabels. Invariant: the original is
    always recoverable from ``.pre-relabel.bak``.
    """
    bak = path.parent / (path.name + ".pre-relabel.bak")
    if not bak.exists():
        shutil.copy2(path, bak)
    return bak


def relabel_run(run_dir: Path, labels: list[str] | None = None) -> dict:
    """Relabel ``temperature`` -> ``None`` for the target model labels in a completed run.

    Returns a summary dict ``{"labels", "relabeled_panels", "relabeled_calls"}``. Idempotent:
    a second run relabels nothing (already None) and leaves files untouched.
    """
    run_dir = Path(run_dir)
    fig4_path = run_dir / "fig4_data.json"
    if not fig4_path.exists():
        raise FileNotFoundError(
            f"{fig4_path} not found -- refusing to relabel an in-progress/absent run. "
            "Only apply this to a COMPLETED run (fig4_data.json present)."
        )
    targets = labels if labels is not None else _native_labels_from_manifest(run_dir)
    if not targets:
        return {"labels": targets, "relabeled_panels": 0, "relabeled_calls": 0}

    # fig4_data.json: null the temperature on every panel of a target model.
    fig4 = json.loads(fig4_path.read_text())
    n_panels = 0
    for panel in fig4.get("arm_a", []):
        if panel.get("model_label") in targets and panel.get("temperature") is not None:
            panel["temperature"] = None
            n_panels += 1
    if n_panels:
        _backup(fig4_path)
        fig4_path.write_text(json.dumps(fig4, indent=2))

    # arm_a_raw.jsonl: keep the raw evidence consistent with the true condition.
    n_calls = 0
    raw_path = run_dir / "arm_a_raw.jsonl"
    if raw_path.exists():
        rows = [json.loads(line) for line in raw_path.read_text().splitlines() if line.strip()]
        for rec in rows:
            if rec.get("model_label") in targets and rec.get("temperature") is not None:
                rec["temperature"] = None
                n_calls += 1
        if n_calls:
            _backup(raw_path)
            raw_path.write_text("".join(json.dumps(r) + "\n" for r in rows))

    return {"labels": targets, "relabeled_panels": n_panels, "relabeled_calls": n_calls}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Relabel temperature-unsupported model results to native/None in a COMPLETED run."
    )
    parser.add_argument("run_dir", type=Path, help="a completed run dir (holds fig4_data.json)")
    parser.add_argument(
        "--labels",
        nargs="+",
        default=None,
        help="model labels to relabel (default: infer supports_temperature=False from manifest)",
    )
    args = parser.parse_args(argv)
    summary = relabel_run(args.run_dir, labels=args.labels)
    print(f"[relabel] {summary}")


if __name__ == "__main__":
    main()
