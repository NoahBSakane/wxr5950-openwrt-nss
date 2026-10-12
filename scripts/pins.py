#!/usr/bin/env python3
"""Resolve build inputs and rewrite OpenWrt feed declarations."""
import argparse
import json
import re
import sys
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}\Z")
REF = re.compile(r"[A-Za-z0-9_./-]+\Z")
FEED = re.compile(r"^src-[^\s]+\s+(\S+)\s+")
NSS_URL = "https://github.com/JuliusBairaktaris/nss-packages.git"


def read_set(path, name):
    if not path.is_file():
        print(f"WARNING: {path} missing; feeds remain unpinned", file=sys.stderr)
        return {}
    data = json.loads(path.read_text())
    return data.get(name, data if "feeds" in data else {})


def resolve(path, name, ref, builder_ref, output):
    entry = read_set(path, name)
    chosen = {
        "pin_set": name,
        "ref": ref or entry.get("ref", ""),
        "builder_ref": builder_ref or entry.get("builder_ref", ""),
        "feeds": entry.get("feeds", {}),
        "kernel": entry.get("kernel"),
        "versions": entry.get("versions", {}),
    }
    if not ref and entry.get("fork", {}).get("sha"):
        chosen["expected_fork_sha"] = entry["fork"]["sha"]
    if not builder_ref and entry.get("builder", {}).get("sha"):
        chosen["expected_builder_sha"] = entry["builder"]["sha"]
    if not chosen["ref"] or not chosen["builder_ref"]:
        raise ValueError("ref and builder_ref are required when candidate pins are unavailable")
    for name in ("ref", "builder_ref"):
        value = chosen[name]
        if value.startswith("-") or not REF.fullmatch(value) or ".." in value:
            raise ValueError(f"invalid {name}")
    output.write_text(json.dumps(chosen, indent=2, ensure_ascii=False) + "\n")
    print(f"ref={chosen['ref']}\nbuilder_ref={chosen['builder_ref']}")


def rewrite_feeds(path, pins):
    feeds = pins.get("feeds", {})
    lines = path.read_text().splitlines() if path.exists() else []
    seen = set()
    result = []
    for line in lines:
        match = FEED.match(line)
        if match and match.group(1) == "nss":
            continue
        if match and match.group(1) in feeds:
            name = match.group(1)
            if name in seen:
                continue
            value = feeds[name]
            sha = value.get("sha")
            if sha:
                if not SHA.fullmatch(sha):
                    raise ValueError(f"invalid SHA for feed {name}")
                result.append(f"src-git {name} {value['url']}^{sha}")
            else:
                print(f"WARNING: {name} feed has no pin", file=sys.stderr)
                result.append(line)
            seen.add(name)
        else:
            result.append(line)
    for name in sorted(set(feeds) - seen - {"nss"}):
        value = feeds[name]
        sha = value.get("sha")
        if sha:
            if not SHA.fullmatch(sha):
                raise ValueError(f"invalid SHA for feed {name}")
            result.append(f"src-git {name} {value['url']}^{sha}")
        else:
            print(f"WARNING: {name} feed has no pin", file=sys.stderr)
    nss = feeds.get("nss", {})
    sha = nss.get("sha")
    if sha:
        if not SHA.fullmatch(sha):
            raise ValueError("invalid SHA for feed nss")
        result.append(f"src-git nss {nss.get('url', NSS_URL)}^{sha}")
    else:
        print("WARNING: nss feed has no pin; using edma-nss branch", file=sys.stderr)
        result.append(f"src-git nss {NSS_URL};edma-nss")
    path.write_text("\n".join(result) + "\n")


def finalize(path, fork_sha, builder_sha):
    for label, value in (("fork", fork_sha), ("builder", builder_sha)):
        if not SHA.fullmatch(value):
            raise ValueError(f"invalid {label} SHA")
    data = json.loads(path.read_text())
    for name, actual in (("fork", fork_sha), ("builder", builder_sha)):
        expected = data.get(f"expected_{name}_sha")
        if expected and expected != actual:
            raise ValueError(f"{name} tag/ref moved: expected {expected}, got {actual}")
    data["resolved"] = {"fork_sha": fork_sha, "builder_sha": builder_sha}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    res = sub.add_parser("resolve")
    res.add_argument("--pins", type=Path, required=True)
    res.add_argument("--set", default="candidate")
    res.add_argument("--ref", default="")
    res.add_argument("--builder-ref", default="")
    res.add_argument("--output", type=Path, required=True)
    feeds = sub.add_parser("feeds")
    feeds.add_argument("--pins", type=Path, required=True)
    feeds.add_argument("--set", default="candidate")
    feeds.add_argument("--config", type=Path, required=True)
    done = sub.add_parser("finalize")
    done.add_argument("--output", type=Path, required=True)
    done.add_argument("--fork-sha", required=True)
    done.add_argument("--builder-sha", required=True)
    args = parser.parse_args()
    if args.command == "resolve":
        resolve(args.pins, args.set, args.ref, args.builder_ref, args.output)
    elif args.command == "feeds":
        rewrite_feeds(args.config, read_set(args.pins, args.set))
    else:
        finalize(args.output, args.fork_sha, args.builder_sha)


if __name__ == "__main__":
    main()
