"""Build lambda-deployment.zip for Terraform (deps + application code)."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ZIP_NAME = "lambda-deployment.zip"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ZIP_NAME,
        help="Output zip path",
    )
    args = parser.parse_args()
    staging = ROOT / "lambda_staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    req = staging / "requirements.txt"
    subprocess.run(
        [
            "uv",
            "export",
            "--format",
            "requirements-txt",
            "--no-dev",
            "--frozen",
            "-o",
            str(req),
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        ["uv", "pip", "install", "-r", str(req), "--target", str(staging)],
        cwd=ROOT,
        check=True,
    )

    py_files = [
        "main.py",
        "agent.py",
        "llm_clients.py",
        "prompt_templates.py",
        "lambda_handler.py",
    ]
    for name in py_files:
        src = ROOT / name
        if not src.is_file():
            print(f"Missing {src}", file=sys.stderr)
            return 1
        shutil.copy2(src, staging / name)

    mem_src = ROOT / "memory"
    mem_dst = staging / "memory"
    shutil.copytree(mem_src, mem_dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    out_zip = args.output.resolve()
    if out_zip.exists():
        out_zip.unlink()

    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in staging.rglob("*"):
            if path.is_file():
                arc = path.relative_to(staging)
                zf.write(path, arcname=str(arc).replace("\\", "/"))

    shutil.rmtree(staging)
    print(f"Wrote {out_zip} ({out_zip.stat().st_size // 1024} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
