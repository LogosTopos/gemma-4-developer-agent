#!/usr/bin/env python3
"""Restore historical retrieval experiments into a separate workspace; do not run them."""
import argparse
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
OLD_PROJECT = "/Users/topologyw/Documents/Kaggles/gemma_4"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    args = parser.parse_args()
    dst = args.output.resolve()
    if dst.exists() and any(dst.iterdir()):
        raise SystemExit("Output must be empty; historical evidence will not be overwritten.")
    dst.mkdir(parents=True, exist_ok=True)
    mappings = []
    for version in ["v3", "v4"]:
        mappings.extend([
            (ROOT / "candidates" / version, dst / "outputs" / f"submission_{version}"),
            (ROOT / "analysis/2026-09-27-localization" / version, dst / "outputs" / f"{version}_experiments"),
            (ROOT / "scripts/research_archive" / version, dst / "work" / f"{version}_experiments"),
        ])
    mappings.append((ROOT / "scripts/research_archive/data_pack", dst / "outputs/gemma4_experiment_pack/tools"))
    for source, target in mappings:
        shutil.copytree(source, target)
    remapped = []
    for p in list((dst / "work").rglob("*.py")) + list((dst / "outputs/gemma4_experiment_pack/tools").glob("*.py")):
        text = p.read_text()
        if OLD_PROJECT in text:
            p.write_text(text.replace(OLD_PROJECT, str(args.project_root.resolve())))
            remapped.append(str(p.relative_to(dst)))
    (dst / "work/v3_experiments/corpus").mkdir()
    (dst / "provenance.json").write_text(json.dumps({
        "source_repository": str(ROOT), "project_root": str(args.project_root.resolve()),
        "remapped_scripts": remapped, "changes": "Only historical absolute data-root paths are remapped.",
        "not_run": ["corpus extraction", "retrieval benchmarks", "model inference"],
    }, indent=2) + "\n")
    print(f"Prepared {dst}; see scripts/research_archive/README.md before running benchmarks.")


if __name__ == "__main__":
    main()
