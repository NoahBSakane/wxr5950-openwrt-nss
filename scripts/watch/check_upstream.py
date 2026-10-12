#!/usr/bin/env python3
"""Read upstream GitHub metadata and notify one Issue on a changed digest."""
import argparse
import base64
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from classify import classify_change, installed_match, package_directory, security_severity

ROOT = Path(__file__).resolve().parents[2]
ISSUE_TITLE = "[upstream-watch] WXR-5950AX12 upstream changes"
VERSION_FILES = {
    "kernel": ("openwrt/openwrt", "target/linux/generic/kernel-6.18"),
    "openssl": ("openwrt/openwrt", "package/libs/openssl/Makefile"),
    "dnsmasq": ("openwrt/openwrt", "package/network/services/dnsmasq/Makefile"),
    "hostapd": ("openwrt/openwrt", "package/network/services/hostapd/Makefile"),
    "tailscale": ("openwrt/packages", "net/tailscale/Makefile"),
    "curl": ("openwrt/packages", "net/curl/Makefile"),
}


def gh_api(path, method="GET", payload=None):
    command = ["gh", "api", "-X", method, path]
    if payload is not None:
        command += ["--input", "-"]
    data = json.dumps(payload).encode() if payload is not None else None
    result = subprocess.run(command, input=data, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"gh api {method} {path} failed: {result.stderr.decode(errors='replace').strip()}")
    return json.loads(result.stdout)


def pages(api, path, limit=20):
    items = []
    for page in range(1, limit + 1):
        join = "&" if "?" in path else "?"
        chunk = api(f"{path}{join}per_page=100&page={page}")
        if not isinstance(chunk, list):
            raise ValueError(f"expected list: {path}")
        items.extend(chunk)
        if len(chunk) < 100:
            return items
    raise RuntimeError(f"pagination limit reached: {path}")


def read_names(path):
    names = set()
    for line in path.read_text().splitlines():
        value = line.split("#", 1)[0].strip()
        if value:
            names.add(value.split("=", 1)[0])
    return names


def read_make_value(content, key):
    match = re.search(rf"(?m)^{re.escape(key)}\s*[:?+]?=\s*(\S+)", content)
    return match.group(1) if match else None


def versions(api, heads):
    values = {}
    for name, (repo, path) in VERSION_FILES.items():
        ref = heads[repo]
        item = api(f"repos/{repo}/contents/{path}?ref={ref}")
        content = base64.b64decode(item["content"]).decode()
        if name == "kernel":
            suffix = read_make_value(content, "LINUX_VERSION-6.18")
            value = "6.18" + suffix if suffix else None
        elif name == "dnsmasq":
            value = read_make_value(content, "PKG_UPSTREAM_VERSION")
        elif name == "hostapd":
            date = read_make_value(content, "PKG_SOURCE_DATE")
            sha = read_make_value(content, "PKG_SOURCE_VERSION")
            value = f"{date}/{sha}" if date and sha else None
        else:
            value = read_make_value(content, "PKG_VERSION")
        if not value:
            raise ValueError(f"version not found in {repo}/{path}")
        values[name] = value
    return values


def tag_commit(api, repo, tag_name):
    # Commits endpoint peels annotated tags, while matching-refs exposes
    # the original object SHA. Keep both to detect a retag to the same commit.
    return api(f"repos/{repo}/commits/{tag_name}")["sha"]


def complete_tree_diff(api, repo, base, head):
    """Compare complete Git trees when compare.files reaches GitHub's 300-file cap."""
    trees = []
    for revision in (base, head):
        commit = api(f"repos/{repo}/git/commits/{revision}")
        tree = api(f"repos/{repo}/git/trees/{commit['tree']['sha']}?recursive=1")
        if tree.get("truncated"):
            raise RuntimeError(f"recursive tree truncated for {repo}@{revision}")
        trees.append({item["path"]: (item["sha"], item["mode"], item["type"])
                      for item in tree["tree"] if item["type"] != "tree"})
    before, after = trees
    return sorted(path for path in before.keys() | after.keys()
                  if before.get(path) != after.get(path))


def repository_snapshot(api, requested_repo, pinned_sha, installed, previous):
    metadata = api(f"repos/{requested_repo}")
    repo = metadata["full_name"]
    branch = metadata["default_branch"]
    head = api(f"repos/{repo}/commits/{branch}")["sha"]
    raw_tags = pages(api, f"repos/{repo}/git/matching-refs/tags/archive/")
    tags = {}
    for item in raw_tags:
        name = item["ref"].removeprefix("refs/tags/")
        tags[name] = {
            "object_sha": item["object"]["sha"],
            "commit_sha": tag_commit(api, repo, name),
        }
    result = {
        "requested": requested_repo, "full_name": repo,
        "archived": metadata["archived"], "default_branch": branch,
        "head": head, "tags": tags,
    }
    changes = []
    if repo != requested_repo:
        changes.append({"kind": "renamed", "repo": requested_repo, "to": repo, "class": "R"})
    if metadata["archived"] and not previous:
        changes.append({"kind": "archived", "repo": repo, "class": "R"})
    if previous:
        if previous.get("full_name") != repo:
            changes.append({"kind": "renamed", "repo": requested_repo, "to": repo, "class": "R"})
        if previous.get("default_branch") != branch:
            changes.append({"kind": "default_branch", "repo": repo, "to": branch, "class": "R"})
        if previous.get("archived") != metadata["archived"]:
            changes.append({"kind": "archived_changed", "repo": repo,
                            "to": metadata["archived"], "class": "R"})
        for name in previous.get("tags", {}).keys() - tags.keys():
            changes.append({"kind": "tag_removed", "repo": repo, "tag": name, "class": "R"})
        for name, value in tags.items():
            old = previous.get("tags", {}).get(name)
            if old and old != value:
                changes.append({"kind": "tag_moved", "repo": repo, "tag": name,
                                "before": old, "after": value, "class": "R"})
            elif old is None:
                changes.append({"kind": "tag_added", "repo": repo, "tag": name, "class": "R"})
    if pinned_sha:
        comparison = api(f"repos/{repo}/compare/{pinned_sha}...{head}")
        commit_messages = "\n".join(item.get("commit", {}).get("message", "")
                                    for item in comparison.get("commits", []))
        result["compare_status"] = comparison["status"]
        result["ahead_by"] = comparison.get("ahead_by", 0)
        files = [item["filename"] for item in comparison.get("files", [])]
        if len(files) >= 300:
            files = complete_tree_diff(api, repo, pinned_sha, head)
            result["files_source"] = "complete_git_trees"
        else:
            result["files_source"] = "compare"
        result["changed_files"] = files
        if comparison["status"] == "diverged":
            changes.append({"kind": "diverged", "repo": repo, "class": "R"})
        if files:
            grade, grades = classify_change(repo, files, "", installed)
            matched = sorted({package for path in files
                              for package in installed_match(package_directory(repo, path), installed)})
            event = {"kind": "files", "repo": repo, "class": grade,
                     "paths": grades, "installed_matches": matched}
            if grade == "S" and any("openssh" in path.lower() for path in files):
                event["severity"] = security_severity("openssh", commit_messages)
            changes.append(event)
    return result, changes


def advisories(api, previous_seen, installed):
    found = pages(api, "repos/openwrt/openwrt/security-advisories")
    by_id = {item["ghsa_id"]: item for item in found}
    changes = []
    for ghsa_id in sorted(set(by_id) - set(previous_seen)):
        item = by_id[ghsa_id]
        summary = item.get("summary") or ""
        description = item.get("description") or ""
        haystack = (summary + " " + description).lower()
        aliases = {"openssl": ("openssl",), "openssh": ("openssh",),
                   "hostapd": ("hostapd", "wpad-"), "dnsmasq": ("dnsmasq",),
                   "tailscale": ("tailscale",), "curl": ("curl",)}
        matches = sorted(name for name in installed
                         if name.lower() in haystack or any(
                             term in haystack and name.startswith(prefix)
                             for term, prefixes in aliases.items() for prefix in prefixes
                             if name.startswith(prefix)))
        changes.append({
            "kind": "ghsa", "id": ghsa_id, "summary": summary,
            "url": item.get("html_url"), "installed_matches": matches,
            "class": "要オーナー確認" if matches else "S",
            "patch_status": "未判定",
        })
    return sorted(by_id), changes


def build_snapshot(api, pins, prior, installed):
    candidate = pins["candidate"]
    entries = [
        ("fork", candidate["fork"]["repo"], candidate["fork"]["sha"]),
        ("builder", candidate["builder"]["repo"], candidate["builder"]["sha"]),
    ] + [(name, value["repo"], value["sha"]) for name, value in candidate["feeds"].items()]
    if "upstream_openwrt" in candidate:
        value = candidate["upstream_openwrt"]
        entries.append(("upstream_openwrt", value["repo"], value["sha"]))
    prior_repos = prior.get("snapshot", {}).get("repos", {})
    repos = {}
    events = []
    heads = {}
    for name, repo, sha in entries:
        info, changes = repository_snapshot(api, repo, sha, installed, prior_repos.get(name))
        repos[name] = info
        heads[info["full_name"]] = info["head"]
        events += changes
        if info["head"] != sha:
            events.append({"kind": "pin_gap", "repo": info["full_name"],
                           "pin": sha, "head": info["head"], "class": "要オーナー確認"})
    if "openwrt/openwrt" not in heads:
        main = api("repos/openwrt/openwrt")
        heads["openwrt/openwrt"] = api(f"repos/openwrt/openwrt/commits/{main['default_branch']}")["sha"]
    current_versions = versions(api, heads)
    for name, current in current_versions.items():
        pinned = candidate["kernel"] if name == "kernel" else candidate["versions"][name]
        if current != pinned:
            events.append({"kind": "version", "component": name, "pinned": pinned,
                           "upstream": current, "class": "要オーナー確認"})
    seen, new_advisories = advisories(api, prior.get("seen_ghsa", []), installed)
    events += new_advisories
    return {
        "repos": repos, "openwrt_main_sha": heads["openwrt/openwrt"],
        "versions": current_versions, "ghsa_ids": seen,
    }, events


def digest(snapshot):
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def issue_body(snapshot, events, value):
    lines = ["候補 pins と上流の週次比較です。実機への書き込みやビルドは行いません。",
             "", f"Digest: `{value}`", "",
             "分類: S=セキュリティ、B=当方に効く修正、R=挙動要確認、N=他機種のみ。未分類は要オーナー確認です。",
             "GHSA の修正済み判定は自動で行いません。", ""]
    for event in events[:100]:
        shown = dict(event)
        if "paths" in shown and len(shown["paths"]) > 20:
            shown["path_count"] = len(shown["paths"])
            shown["paths"] = shown["paths"][:20]
        line = f"- **{event['class']}** `{event['kind']}`: `{json.dumps(shown, ensure_ascii=False, sort_keys=True)}`"
        if sum(map(len, lines)) + len(line) > 55000:
            lines.append("- 詳細は state ブランチの JSON を確認してください。")
            break
        lines.append(line)
    if len(events) > 100:
        lines.append(f"- 残り {len(events)-100} 件は state JSON を確認してください。")
    if not events:
        lines.append("- 分類対象の新規事象はありません。")
    lines += ["", f"観測した上流 SHA: `{snapshot['openwrt_main_sha']}`"]
    return "\n".join(lines)


def notify(api, repository, prior, snapshot, events, value):
    number = prior.get("issue_number")
    body = issue_body(snapshot, events, value)
    if number is None:
        # Recover a previous Issue if state was lost; never create duplicates.
        for issue in pages(api, f"repos/{repository}/issues?state=all"):
            if issue.get("title") == ISSUE_TITLE and "pull_request" not in issue:
                number = issue["number"]
                break
    if number is None:
        issue = api(f"repos/{repository}/issues", "POST", {"title": ISSUE_TITLE, "body": body})
        number = issue["number"]
    else:
        api(f"repos/{repository}/issues/{number}", "PATCH", {"title": ISSUE_TITLE, "body": body})
    return number


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pins", type=Path, default=ROOT / "config/pins.json")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--notify", action="store_true")
    parser.add_argument("--repository", help="owner/repo for the single Issue")
    args = parser.parse_args()
    prior = json.loads(args.state.read_text()) if args.state.exists() else {}
    pins = json.loads(args.pins.read_text())
    installed = read_names(ROOT / "config/packages.txt") | read_names(ROOT / "config/installed-watch.txt")
    snapshot, events = build_snapshot(gh_api, pins, prior, installed)
    value = digest(snapshot)
    changed = value != prior.get("notified_digest")
    number = prior.get("issue_number")
    if changed and args.notify:
        if not args.repository:
            parser.error("--repository is required with --notify")
        number = notify(gh_api, args.repository, prior, snapshot, events, value)
    result = {
        "schema": 1, "checked_at": datetime.now(timezone.utc).isoformat(),
        "pins": pins, "snapshot": snapshot, "events": events,
        "notified_digest": value if args.notify or not changed else prior.get("notified_digest"),
        "issue_number": number,
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"changed": changed, "digest": value, "issue_number": number}))


if __name__ == "__main__":
    main()
