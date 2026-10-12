"""Conservative path and installed-package classification."""
import json
import re
from pathlib import Path

RULES = json.loads((Path(__file__).with_name("rules.json")).read_text())
ORDER = {"N": 0, "B": 1, "R": 2, "S": 3, "要オーナー確認": 4}
GENERIC_ADVISORY_NAMES = {"sed", "awk", "ip", "curl", "luci"}


def exact_word(text, name):
    """Match a complete package word; letters, digits and hyphens stay together."""
    return bool(re.search(r"(?<![a-z0-9-])" + re.escape(name) + r"(?![a-z0-9-])",
                          text, re.IGNORECASE))


def advisory_matches(item, installed):
    summary = item.get("summary") or ""
    targets = {vulnerability.get("package", {}).get("name", "").lower()
               for vulnerability in item.get("vulnerabilities", [])
               if isinstance(vulnerability.get("package"), dict)}
    targets.discard("")
    if not targets:
        # OpenWrt often titles advisories "package: problem"; a slash may
        # separate two affected packages, as in "odhcpd/LuCI: ...".
        heading = re.match(r"^\s*([a-z0-9][a-z0-9+._/-]*):\s", summary, re.I)
        if heading:
            targets = set(heading.group(1).lower().split("/"))
    leading = re.match(r"^\s*([a-z0-9][a-z0-9-]*)", summary, re.I)
    first_word = leading.group(1).lower() if leading else ""

    def matches(name, target):
        name = name.lower()
        if name == target:
            return True
        if target == "hostapd" and (name == "hostapd-common" or name.startswith("wpad-")):
            return True
        if target == "openssh" and name.startswith("openssh-"):
            return True
        return False

    matched = []
    for name in installed:
        if targets:
            relevant = any(matches(name, target) for target in targets)
        elif name.lower() in GENERIC_ADVISORY_NAMES:
            relevant = name.lower() == first_word
        else:
            relevant = exact_word(summary, name)
            if name.lower() == "hostapd-common" or name.lower().startswith("wpad-"):
                relevant = relevant or exact_word(summary, "hostapd")
            if name.lower().startswith("openssh-"):
                relevant = relevant or exact_word(summary, "openssh")
        if relevant:
            matched.append(name)
    return sorted(targets), sorted(matched)


def package_directory(repo, path):
    parts = path.split("/")
    if repo == "openwrt/luci" and len(parts) > 1 and parts[0] in {"applications", "modules", "themes", "protocols"}:
        return parts[1]
    if repo in {"openwrt/packages", "openwrt/routing", "openwrt/telephony", "openwrt/video"} and len(parts) > 1:
        if parts[0] in {"net", "utils", "libs", "multimedia", "lang", "admin", "sound"}:
            return parts[1]
    return None


def installed_match(directory, installed):
    if not directory:
        return []
    normalized = directory.removeprefix("luci-app-")
    return sorted(name for name in installed
                  if name == directory or name.startswith(directory + "-")
                  or directory.startswith(name + "-")
                  or (directory == "openssh" and name.startswith("openssh-"))
                  or (directory == "hostapd" and name in {"wpad-openssl", "hostapd-common"})
                  or (normalized != directory and name == directory))


def classify(repo, path, message="", installed=()):
    lower = (message + " " + path).lower()
    if re.search(r"\bcve-\d|\bghsa-|security|vulnerability", lower):
        return "S"
    if "openssh" in lower:
        return "S"
    if any(re.search(pattern, path) for pattern in RULES["behavior_paths"]):
        return "R"
    if installed_match(package_directory(repo, path), installed):
        return "B"
    if any(f"/{target}/" in f"/{path}/" for target in RULES["other_targets"]):
        return "N"
    return "要オーナー確認"


def classify_change(repo, files, message, installed):
    grades = [(classify(repo, path, message, installed), path) for path in files]
    if not grades:
        return "要オーナー確認", []
    # Unknown always remains visible, even if a known path is present.
    return max((grade for grade, _ in grades), key=ORDER.get), grades


def security_severity(path, message=""):
    context = (path + " " + message).lower()
    if "openssh" in context and not re.search(r"cve-|ghsa-|vulnerability", context):
        return "low"
    return "undetermined"
