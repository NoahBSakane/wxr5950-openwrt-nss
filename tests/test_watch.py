import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/watch"))
from classify import classify, classify_change, installed_match, package_directory, security_severity
from check_upstream import advisories, complete_tree_diff, digest, notify, repository_snapshot

spec = importlib.util.spec_from_file_location("pins", ROOT / "scripts/pins.py")
pins = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pins)

A = "a" * 40
B = "b" * 40
C = "c" * 40
D = "d" * 40


class WatchTests(unittest.TestCase):
    def test_today_classifications(self):
        installed = {"openssh-server", "netifd", "kmod-qca-mcs"}
        self.assertEqual(classify("openwrt/openwrt", "package/network/services/openssh/Makefile",
                                  "OpenSSH 10.6 update", installed), "S")
        self.assertEqual(security_severity("package/network/services/openssh/Makefile",
                                           "OpenSSH 10.6 update"), "low")
        self.assertEqual(classify("openwrt/openwrt", "package/network/config/netifd/Makefile",
                                  "move MAC assignment", installed), "R")
        self.assertEqual(classify("JuliusBairaktaris/openwrt-ppe-nss",
                                  "package/kernel/qca-mcs/Makefile", "remove qca-mcs", installed), "R")
        self.assertEqual(classify_change("openwrt/openwrt",
                                         ["target/linux/mediatek/image/Makefile",
                                          "target/linux/ramips/dts/board.dts"], "", installed)[0], "N")
        self.assertEqual(classify("openwrt/openwrt", "include/new-build-rule.mk", "", installed),
                         "要オーナー確認")

    def test_installed_feed_directory(self):
        self.assertEqual(package_directory("openwrt/packages", "net/openssh/Makefile"), "openssh")
        self.assertEqual(installed_match("openssh", {"openssh-server", "curl"}),
                         ["openssh-server"])
        self.assertEqual(classify("openwrt/packages", "net/tailscale/Makefile", "",
                                  {"tailscale"}), "B")

    def test_rename_divergence_and_tag_movement(self):
        old = {"full_name": "JuliusBairaktaris/openwrt-nss-edma",
               "default_branch": "nss-edma-rework",
               "tags": {"archive/nss-edma-rework-final":
                        {"object_sha": A, "commit_sha": B}}}

        def api(path):
            if path == "repos/JuliusBairaktaris/openwrt-nss-edma":
                return {"full_name": "JuliusBairaktaris/openwrt-ppe-nss",
                        "archived": False, "default_branch": "ppe-nss"}
            if path == "repos/JuliusBairaktaris/openwrt-ppe-nss/commits/ppe-nss":
                return {"sha": C}
            if path.startswith("repos/JuliusBairaktaris/openwrt-ppe-nss/git/matching-refs/"):
                return [{"ref": "refs/tags/archive/nss-edma-rework-final",
                         "object": {"sha": D}}]
            if path == "repos/JuliusBairaktaris/openwrt-ppe-nss/commits/archive/nss-edma-rework-final":
                return {"sha": B}
            if path == f"repos/JuliusBairaktaris/openwrt-ppe-nss/compare/{A}...{C}":
                return {"status": "diverged", "ahead_by": 2, "files": []}
            raise AssertionError(path)

        snapshot, events = repository_snapshot(
            api, "JuliusBairaktaris/openwrt-nss-edma", A, set(), old)
        self.assertEqual(snapshot["compare_status"], "diverged")
        self.assertEqual(snapshot["tags"]["archive/nss-edma-rework-final"],
                         {"object_sha": D, "commit_sha": B})
        kinds = {event["kind"] for event in events}
        self.assertTrue({"renamed", "default_branch", "tag_moved", "diverged"} <= kinds)
        self.assertEqual(len([e for e in events if e["kind"] == "tag_moved"]), 1)

    def test_new_ghsa_deduplicated_and_never_assumed_patched(self):
        def api(path):
            self.assertEqual(path, "repos/openwrt/openwrt/security-advisories?per_page=100&page=1")
            return [{"ghsa_id": "GHSA-abc", "summary": "dnsmasq issue",
                     "description": "", "vulnerabilities": [{"patched_versions": ""}]},
                    {"ghsa_id": "GHSA-abc", "summary": "dnsmasq issue",
                     "description": "", "vulnerabilities": []},
                    {"ghsa_id": "GHSA-old", "summary": "old issue"}]

        seen, events = advisories(api, ["GHSA-old"], {"dnsmasq"})
        self.assertEqual(seen, ["GHSA-abc", "GHSA-old"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["class"], "要オーナー確認")
        self.assertEqual(events[0]["patch_status"], "未判定")
        self.assertEqual(advisories(api, seen, {"dnsmasq"})[1], [])

    def test_ghsa_component_alias_matches_installed_variant(self):
        def api(path):
            return [{"ghsa_id": "GHSA-hostapd", "summary": "hostapd issue",
                     "description": "", "vulnerabilities": []}]
        _, events = advisories(api, [], {"wpad-openssl", "hostapd-common"})
        self.assertEqual(events[0]["installed_matches"],
                         ["hostapd-common", "wpad-openssl"])

    def test_issue_reused_after_state_loss(self):
        calls = []
        def api(path, method="GET", payload=None):
            calls.append((path, method))
            if path == "repos/owner/build/issues?state=all&per_page=100&page=1":
                return [{"title": "[upstream-watch] WXR-5950AX12 upstream changes",
                         "number": 7}]
            if path == "repos/owner/build/issues/7" and method == "PATCH":
                return {"number": 7}
            raise AssertionError((path, method))
        number = notify(api, "owner/build", {}, {"openwrt_main_sha": A}, [], B)
        self.assertEqual(number, 7)
        self.assertNotIn(("repos/owner/build/issues", "POST"), calls)

    def test_digest_ignores_json_order(self):
        self.assertEqual(digest({"a": 1, "b": 2}), digest({"b": 2, "a": 1}))

    def test_complete_tree_diff_at_compare_limit(self):
        def api(path):
            if path.endswith(f"/git/commits/{A}"):
                return {"tree": {"sha": C}}
            if path.endswith(f"/git/commits/{B}"):
                return {"tree": {"sha": D}}
            if path.endswith(f"/git/trees/{C}?recursive=1"):
                return {"truncated": False, "tree": [
                    {"path": "net/openssh/Makefile", "sha": A, "mode": "100644", "type": "blob"},
                    {"path": "net/curl/Makefile", "sha": C, "mode": "100644", "type": "blob"}]}
            if path.endswith(f"/git/trees/{D}?recursive=1"):
                return {"truncated": False, "tree": [
                    {"path": "net/openssh/Makefile", "sha": B, "mode": "100644", "type": "blob"},
                    {"path": "net/curl/Makefile", "sha": C, "mode": "100644", "type": "blob"}]}
            raise AssertionError(path)
        self.assertEqual(complete_tree_diff(api, "owner/repo", A, B),
                         ["net/openssh/Makefile"])

    def test_pins_resolve_and_feed_rewrite(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            base = Path(temp)
            source = base / "pins.json"
            output = base / "pins-used.json"
            conf = base / "feeds.conf"
            source.write_text(json.dumps({"candidate": {
                "ref": "archive/final", "builder_ref": "archive/builder",
                "feeds": {"packages": {"url": "https://example.invalid/packages.git", "sha": A},
                          "nss": {"url": "https://example.invalid/nss.git", "sha": B}},
            }}))
            conf.write_text("src-git packages https://example.invalid/packages.git;master\n"
                            "src-git nss https://example.invalid/nss.git;edma-nss\n")
            pins.resolve(source, "candidate", "", "", output)
            pins.rewrite_feeds(conf, json.loads(output.read_text()))
            self.assertIn(f"src-git packages https://example.invalid/packages.git^{A}", conf.read_text())
            self.assertIn(f"src-git nss https://example.invalid/nss.git^{B}", conf.read_text())
            self.assertNotIn(";edma-nss", conf.read_text())
            pins.finalize(output, C, D)
            self.assertEqual(json.loads(output.read_text())["resolved"]["fork_sha"], C)
            pins.resolve(source, "candidate", C, D, output)
            self.assertEqual(json.loads(output.read_text())["ref"], C)

    def test_moved_default_tag_fails_before_build(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            base = Path(temp)
            source = base / "pins.json"
            output = base / "pins-used.json"
            source.write_text(json.dumps({"candidate": {
                "ref": "archive/final", "builder_ref": "archive/builder",
                "fork": {"sha": A}, "builder": {"sha": B}, "feeds": {},
            }}))
            pins.resolve(source, "candidate", "", "", output)
            with self.assertRaisesRegex(ValueError, "fork tag/ref moved"):
                pins.finalize(output, C, B)


if __name__ == "__main__":
    unittest.main()
