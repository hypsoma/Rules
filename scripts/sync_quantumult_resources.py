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
    parser.add_argument(
        "--report",
        default=".sync-report.json",
        help="JSON file to write the sync result report to.",
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


def read_previous_manifest(manifest_path: Path) -> list[dict[str, object]]:
    if not manifest_path.exists():
        return []
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def sync_resources(
    resources: list[Resource],
    timeout: int,
    repo_root: Path,
) -> dict[str, list[dict[str, str]] | list[str]]:
    resource_by_path = {resource.target_path.as_posix(): resource for resource in resources}
    updated_files: list[str] = []
    unchanged_files: list[str] = []
    failed_files: list[dict[str, str]] = []

    with tempfile.TemporaryDirectory(prefix="quantumult-sync-") as temp_dir:
        temp_root = Path(temp_dir)
        for resource in resources:
            try:
                content = fetch_resource(resource.url, timeout)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                failed_files.append(
                    {
                        "path": resource.target_path.as_posix(),
                        "url": resource.url,
                        "error": str(exc),
                    }
                )
                print(f"Failed {resource.url}: {exc}", file=sys.stderr)
                continue

            temp_target = temp_root / resource.target_path
            temp_target.parent.mkdir(parents=True, exist_ok=True)
            temp_target.write_bytes(content)

            target = repo_root / resource.target_path
            if target.exists() and target.read_bytes() == content:
                unchanged_files.append(resource.target_path.as_posix())
                print(f"Unchanged {resource.url} -> {resource.target_path}")
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(temp_target, target)
            updated_files.append(resource.target_path.as_posix())
            print(f"Updated {resource.url} -> {resource.target_path}")

    return {
        "updated_files": sorted(updated_files),
        "unchanged_files": sorted(unchanged_files),
        "failed_files": sorted(failed_files, key=lambda item: item["path"]),
        "managed_paths": sorted(resource_by_path),
    }


def remove_stale_files(
    previous_manifest: list[dict[str, object]],
    current_paths: set[str],
    repo_root: Path,
) -> list[str]:
    previous_paths = {
        str(item["path"])
        for item in previous_manifest
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    removed_files: list[str] = []
    for relative_path in sorted(previous_paths - current_paths):
        target = repo_root / relative_path
        if not target.exists():
            continue
        target.unlink()
        removed_files.append(relative_path)
        parent = target.parent
        while parent != repo_root and parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    return removed_files


def write_report(report_path: Path, report: dict[str, object]) -> None:
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    repo_root = Path.cwd()
    config_path = repo_root / args.config
    manifest_path = repo_root / args.manifest
    report_path = repo_root / args.report

    if not config_path.exists():
        print(f"Config file not found: {config_path}", file=sys.stderr)
        return 1

    try:
        resources = extract_resources(config_path)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    previous_manifest = read_previous_manifest(manifest_path)
    try:
        sync_result = sync_resources(resources, args.timeout, repo_root)
    except OSError as exc:
        print(f"Sync failed: {exc}", file=sys.stderr)
        return 1

    removed_files = remove_stale_files(
        previous_manifest,
        set(sync_result["managed_paths"]),
        repo_root,
    )
    write_manifest(resources, manifest_path)
    report = {
        "updated_files": sync_result["updated_files"],
        "removed_files": removed_files,
        "failed_files": sync_result["failed_files"],
        "unchanged_files": sync_result["unchanged_files"],
    }
    write_report(report_path, report)
    print(
        "Synced "
        f"{len(resources)} resources: "
        f"{len(sync_result['updated_files'])} updated, "
        f"{len(removed_files)} removed, "
        f"{len(sync_result['failed_files'])} failed, "
        f"{len(sync_result['unchanged_files'])} unchanged."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
