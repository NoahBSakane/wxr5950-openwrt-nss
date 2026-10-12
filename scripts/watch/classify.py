"""Conservative path and installed-package classification."""
import json
import re
from pathlib import Path

RULES = json.loads((Path(__file__).with_name("rules.json")).read_text())
ORDER = {"N": 0, "B": 1, "R": 2, "S": 3, "要オーナー確認": 4}


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
