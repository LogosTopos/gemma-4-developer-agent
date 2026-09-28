#!/usr/bin/env python3
"""Fetch the exact Roman public artifact used for D0; never submit or run it."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import zipfile

REF = "romanrozen/gemma-eda-baseline-for-a-start-lb-top-1"
SHA256 = "f3534769cd8c7761b8ae83722b0f2fd381c0349587a10e84bd63e0554a4a7aa4"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("dist/roman-public"))
    parser.add_argument("--from-file", type=Path, help="Use an already downloaded original ZIP")
    parser.add_argument("--kaggle", default="kaggle", help="Kaggle CLI executable")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="roman-public-") as tmp:
        if args.from_file:
            source = args.from_file
        else:
            subprocess.run([args.kaggle, "kernels", "output", REF, "-p", tmp,
                            "--file-pattern", r"^submission\.zip$"], check=True)
            source = Path(tmp) / "submission.zip"
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != SHA256:
            raise SystemExit(f"Artifact changed: expected {SHA256}, got {digest}. Do not label this D0.")
        if args.output.exists() and any(args.output.iterdir()):
            raise SystemExit("Output directory is not empty; choose a fresh directory.")
        args.output.mkdir(parents=True, exist_ok=True)
        archive = args.output / "submission.zip"
        shutil.copyfile(source, archive)
        bundle = args.output / "bundle"
        bundle.mkdir()
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                rel = PurePosixPath(info.filename)
                if rel.is_absolute() or ".." in rel.parts or (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise SystemExit(f"Unsafe archive member: {info.filename}")
            z.extractall(bundle)
        (args.output / "provenance.json").write_text(json.dumps({
            "source": f"https://www.kaggle.com/code/{REF}",
            "artifact": "submission.zip", "sha256": digest,
            "experiment_id": "D0-ROMAN-EXACT", "submission_id": 56641493,
            "modifications": [], "note": "No score is guaranteed; preserve source attribution."
        }, indent=2) + "\n")
        print(f"Verified original ZIP: {archive}\nExtracted for inspection: {bundle}\nSHA256: {digest}")


if __name__ == "__main__":
    main()
