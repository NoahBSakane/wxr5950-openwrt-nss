#!/usr/bin/env python3
"""Generate the public image overlay and verify its build-root copy."""

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
DEFAULT_MAP = REPO / "config/bake-map.txt"
BOOT_SCRIPT = REPO / "scripts/bake/90-wxr5950-bake"
BOOT_PATH = "/etc/uci-defaults/90-wxr5950-bake"
MANIFEST_PATH = "/etc/wxr5950-baked-paths"
SECRET_PATTERNS = (
    r"[[:alnum:]_.%+-]+@[[:alnum:].-]+\.[[:alpha:]]{2,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"https?://[^/[:space:]]*ntfy[^/[:space:]]*/[A-Za-z0-9_-]{8,}",
    r"(^|[^A-Za-z0-9_-])[A-Za-z0-9_-]{48,}([^A-Za-z0-9_-]|$)",
    r"(TOKEN|PASSWORD|SECRET|API_KEY)=[\"']?[A-Za-z0-9_/-]{8,}",
)


def read_map(path):
    entries = []
    sources, destinations = set(), set()
    for number, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) != 3:
            raise ValueError(f"Invalid bake map line {number}")
        source, target, mode = fields
        if ("/" in source or source in (".", "..") or not target.startswith("/")
                or ".." in Path(target).parts or target == "/"
                or not re.fullmatch(r"0[0-7]{3}", mode)
                or source in sources or target in destinations
                or target in (BOOT_PATH, MANIFEST_PATH)):
            raise ValueError(f"Unsafe or duplicate bake map line {number}")
        sources.add(source)
        destinations.add(target)
        entries.append((source, target, int(mode, 8)))
    if not entries:
        raise ValueError("Empty bake map")
    return entries


def scan_secrets(paths):
    for path in paths:
        for pattern in SECRET_PATTERNS:
            result = subprocess.run(["grep", "-E", "-q", "--", pattern, str(path)],
                                    check=False, capture_output=True)
            if result.returncode == 0:
                raise ValueError(f"Secret or personal identifier pattern in {path.name}")
            if result.returncode != 1:
                raise OSError(f"Secret scan failed for {path.name}: grep returned {result.returncode}")


def sync(source_dir, map_path=DEFAULT_MAP, output=REPO / "files"):
    entries = read_map(map_path)
    source_dir, output = Path(source_dir), Path(output)
    if not source_dir.is_dir():
        raise ValueError("Router scripts source is not a directory")
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=".bake-stage-") as tmp:
        stage = Path(tmp) / "files"
        stage.mkdir()
        paths = []
        for source, target, mode in entries:
            original = source_dir / source
            if not original.is_file() or original.is_symlink():
                raise ValueError(f"Missing or unsafe source: {source}")
            destination = stage / target.lstrip("/")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, destination)
            destination.chmod(mode)
            paths.append(destination)
        boot = stage / BOOT_PATH.lstrip("/")
        boot.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(BOOT_SCRIPT, boot)
        boot.chmod(0o755)
        paths.append(boot)
        scan_secrets(paths)
        manifest = stage / MANIFEST_PATH.lstrip("/")
        manifest.write_text("".join(f"{path}\n" for path in sorted(
            [target for _, target, _ in entries] + [BOOT_PATH, MANIFEST_PATH])))
        manifest.chmod(0o644)
        if output.exists():
            if not output.is_dir() or output.is_symlink():
                raise ValueError("Output files path is not a directory")
            shutil.rmtree(output)
        stage.rename(output)
    print(f"Generated {len(entries) + 2} baked paths in {output}")


def hashes(files_dir, output):
    files_dir = Path(files_dir)
    paths = (files_dir / MANIFEST_PATH.lstrip("/")).read_text().splitlines()
    output = Path(output)
    output.write_text("".join(
        f"{hashlib.sha256((files_dir / path.lstrip('/')).read_bytes()).hexdigest()}  {path}\n"
        for path in paths
    ))
    return paths


def verify_rootfs(files_dir, build_dir, hashes_path):
    paths = hashes(files_dir, hashes_path)
    manifest_rel = MANIFEST_PATH.lstrip("/")
    candidates = []
    for directory, subdirs, filenames in os.walk(build_dir):
        if "wxr5950-baked-paths" in filenames and directory.endswith("/etc"):
            root = Path(directory).parent
            if (root / manifest_rel).is_file():
                candidates.append(root)
        # Build output contains huge package trees; only root directories matter.
        if Path(directory).name.startswith("root-"):
            subdirs[:] = [part for part in subdirs if part in ("etc", "usr")]
    if not candidates:
        print("WARNING: no build rootfs containing the baked manifest was found", file=sys.stderr)
        return
    for root in candidates:
        for path in paths:
            expected = Path(files_dir) / path.lstrip("/")
            actual = root / path.lstrip("/")
            if not actual.is_file() or hashlib.sha256(actual.read_bytes()).digest() != hashlib.sha256(expected.read_bytes()).digest():
                raise ValueError(f"Missing or mismatched baked file in {root}: {path}")
        print(f"Verified {len(paths)} baked paths in {root}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sync_parser = sub.add_parser("sync")
    sync_parser.add_argument("source", type=Path)
    sync_parser.add_argument("--map", type=Path, default=DEFAULT_MAP)
    sync_parser.add_argument("--output", type=Path, default=REPO / "files")
    verify_parser = sub.add_parser("verify-rootfs")
    verify_parser.add_argument("--files", type=Path, default=REPO / "files")
    verify_parser.add_argument("--build-dir", type=Path, required=True)
    verify_parser.add_argument("--hashes", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "sync":
            sync(args.source, args.map, args.output)
        else:
            verify_rootfs(args.files, args.build_dir, args.hashes)
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
