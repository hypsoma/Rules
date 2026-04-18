#!/usr/bin/env python3
"""Sync Quantumult X raw resources referenced by the local config file."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path


SECTION_TO_DIR = {
    "filter_remote": "filter",
    "rewrite_remote": "rewrite",
    "server_remote": "server",
}
RAW_HOST = "raw.githubusercontent.com"


@dataclass(frozen=True)
class Resource:
    line_number: int
    section: str
    url: str

    @property
    def category(self) -> str:
        return SECTION_TO_DIR.get(self.section, self.section or "misc")

    @property
    def filename(self) -> str:
        parsed = urllib.parse.urlparse(self.url)
        return Path(parsed.path).name

    @property
    def target_path(self) -> Path:
        return Path(self.category) / self.filename


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download raw resources from a Quantumult X config file.",
    )
    parser.add_argument(
        "--config",
        default="quantumult_20260331175325-2.conf",
        help="Quantumult X config file to parse.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--manifest",
        default="sources.json",
        help="JSON file to write the resource manifest to.",
    )
    return parser.parse_args()


def extract_resources(config_path: Path) -> list[Resource]:
    resources: list[Resource] = []
    section = ""
    url_pattern = re.compile(r"^(https?://[^,\s]+)")

    for line_number, raw_line in enumerate(config_path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1]
            continue
        match = url_pattern.match(stripped)
        if not match:
            continue
        url = match.group(1)
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc != RAW_HOST:
            continue
        resources.append(Resource(line_number=line_number, section=section, url=url))

    if not resources:
        raise ValueError(f"No raw resources found in {config_path}")

    return resources


def fetch_resource(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "quantumult-resource-sync/1.0",
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def write_temp_downloads(resources: list[Resource], timeout: int, temp_root: Path) -> None:
    for resource in resources:
        target = temp_root / resource.target_path
        target.parent.mkdir(parents=True, exist_ok=True)
        content = fetch_resource(resource.url, timeout)
        target.write_bytes(content)
        print(f"Downloaded {resource.url} -> {resource.target_path}")


def replace_tree(resources: list[Resource], temp_root: Path, repo_root: Path) -> None:
    managed_roots = sorted({resource.category for resource in resources})
    for category in managed_roots:
        shutil.rmtree(repo_root / category, ignore_errors=True)
        shutil.copytree(temp_root / category, repo_root / category)


def write_manifest(resources: list[Resource], manifest_path: Path) -> None:
    manifest = [
        {
            "line_number": resource.line_number,
            "section": resource.section,
            "category": resource.category,
            "url": resource.url,
            "path": resource.target_path.as_posix(),
        }
        for resource in resources
    ]
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    repo_root = Path.cwd()
    config_path = repo_root / args.config
    manifest_path = repo_root / args.manifest

    if not config_path.exists():
        print(f"Config file not found: {config_path}", file=sys.stderr)
        return 1

    try:
        resources = extract_resources(config_path)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        with tempfile.TemporaryDirectory(prefix="quantumult-sync-") as temp_dir:
            temp_root = Path(temp_dir)
            write_temp_downloads(resources, args.timeout, temp_root)
            replace_tree(resources, temp_root, repo_root)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"Sync failed: {exc}", file=sys.stderr)
        return 1

    write_manifest(resources, manifest_path)
    print(f"Synced {len(resources)} resources.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
