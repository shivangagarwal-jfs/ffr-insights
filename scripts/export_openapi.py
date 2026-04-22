#!/usr/bin/env python3
"""Export the OpenAPI spec from the FastAPI app to JSON and YAML files.

Usage:
    python -m scripts.export_openapi              # writes to API_Contract/
    python -m scripts.export_openapi --out-dir .   # custom output directory
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

# Ensure repo root is on sys.path so ``app`` package is importable.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.main import app  # noqa: E402


def _get_openapi_spec() -> dict:
    return app.openapi()


def main() -> None:
    parser = argparse.ArgumentParser(description="Export FFR API OpenAPI spec.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_REPO_ROOT / "API_Contract",
        help="Directory to write the spec files into (default: API_Contract/).",
    )
    args = parser.parse_args()
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    spec = _get_openapi_spec()

    json_path = out_dir / "openapi.json"
    json_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n")
    print(f"  JSON  → {json_path}")

    yaml_path = out_dir / "openapi.yaml"
    yaml_path.write_text(
        yaml.dump(spec, default_flow_style=False, sort_keys=False, allow_unicode=True)
    )
    print(f"  YAML  → {yaml_path}")

    paths = spec.get("paths", {})
    schemas = spec.get("components", {}).get("schemas", {})
    print(f"\n  Endpoints: {len(paths)}  |  Schemas: {len(schemas)}")


if __name__ == "__main__":
    main()
