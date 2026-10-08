import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("configure", ROOT / "scripts/configure.py")
configure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure)


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        # Keep all test writes inside the worktree.
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.common = self.root / "devices/common/config"
        self.group = self.root / "devices/ipq807x-1g/config"
        self.common.parent.mkdir(parents=True)
        self.group.parent.mkdir(parents=True)
        self.common.write_text('CONFIG_PACKAGE_luci=y\nCONFIG_TEST="common"\nCONFIG_PACKAGE_tcpdump=y\n')
        self.group.write_text(
            f'{configure.DEVICE}=y\nCONFIG_TEST="group"\n'
            'CONFIG_TARGET_DEVICE_qualcommax_ipq807x_DEVICE_other=y\n'
            'CONFIG_TARGET_qualcommax_ipq807x_DEVICE_old=y\n'
        )
        self.packages = self.root / "packages.txt"
        self.packages.write_text("# comment\nluci\nluci=y # duplicate\nmdns-repeater=m\ntcpdump-mini\n")
        self.config = self.root / ".config"
        self.required = self.root / "required.txt"

    def prepare(self):
        configure.prepare(self.root, self.packages, self.config, self.required)

    def test_modes_comments_and_duplicates(self):
        self.assertEqual(configure.read_packages(self.packages), {
            "luci": "y", "mdns-repeater": "m", "tcpdump-mini": "y",
        })

    def test_invalid_entries_and_conflicting_modes(self):
        for entry in ("bad/name", "luci=n", "luci=m=y", "=m", "luci\nluci=m"):
            with self.subTest(entry=entry):
                self.packages.write_text(entry)
                with self.assertRaises(ValueError):
                    configure.read_packages(self.packages)

    def test_tcpdump_conflict_including_modules(self):
        self.packages.write_text("tcpdump=m\ntcpdump-mini\n")
        with self.assertRaisesRegex(ValueError, "tcpdump"):
            configure.read_packages(self.packages)

    def test_group_precedence_and_single_device(self):
        self.prepare()
        values = configure.read_config(self.config)
        self.assertEqual(values["CONFIG_TEST"], '"group"')
        self.assertEqual(values[configure.DEVICE], "y")
        enabled = [key for key, value in values.items()
                   if configure.DEVICE_SYMBOL.fullmatch(key) and value == "y"]
        self.assertEqual(enabled, [configure.DEVICE])
        self.assertEqual(values["CONFIG_ATH11K_MEM_PROFILE_1G"], "y")
        self.assertEqual(values["CONFIG_NSS_MEM_PROFILE_HIGH"], "y")
        self.assertEqual(values["CONFIG_TARGET_PER_DEVICE_ROOTFS"], "y")
        self.assertFalse(configure.DEVICE_SYMBOL.fullmatch("CONFIG_TARGET_PER_DEVICE_ROOTFS"))
        self.assertFalse(configure.DEVICE_SYMBOL.fullmatch(
            "CONFIG_TARGET_DEVICE_PACKAGES_qualcommax_ipq807x_DEVICE_buffalo_wxr-5950ax12"))
        self.assertEqual(values["CONFIG_PACKAGE_mdns-repeater"], "m")
        self.assertEqual(values["CONFIG_PACKAGE_tcpdump"], "n")
        configure.verify(self.config, self.required)

    def test_module_overrides_builder_builtin(self):
        self.packages.write_text("luci=m\n")
        self.prepare()
        self.assertEqual(configure.read_config(self.config)["CONFIG_PACKAGE_luci"], "m")

    def test_reports_all_dropped_or_promoted_packages(self):
        self.prepare()
        values = configure.read_config(self.config)
        del values["CONFIG_PACKAGE_luci"]
        values["CONFIG_PACKAGE_mdns-repeater"] = "y"
        configure.write_config(self.config, values)
        with self.assertRaises(ValueError) as caught:
            configure.verify(self.config, self.required)
        self.assertIn("CONFIG_PACKAGE_luci=y", str(caught.exception))
        # m -> y is accepted: the package is still built and is in the image.
        self.assertNotIn("CONFIG_PACKAGE_mdns-repeater=m", str(caught.exception))

    def test_module_promoted_to_builtin_is_accepted(self):
        self.prepare()
        values = configure.read_config(self.config)
        values["CONFIG_PACKAGE_mdns-repeater"] = "y"
        configure.write_config(self.config, values)
        configure.verify(self.config, self.required)

    def test_module_dropped_is_rejected(self):
        self.prepare()
        values = configure.read_config(self.config)
        values["CONFIG_PACKAGE_mdns-repeater"] = "n"
        configure.write_config(self.config, values)
        with self.assertRaises(ValueError):
            configure.verify(self.config, self.required)

    def test_unexpected_devices_in_both_symbol_forms(self):
        self.prepare()
        for symbol in ("CONFIG_TARGET_DEVICE_qualcommax_ipq807x_DEVICE_other",
                       "CONFIG_TARGET_qualcommax_ipq807x_DEVICE_old"):
            with self.subTest(symbol=symbol):
                values = configure.read_config(self.config)
                values[symbol] = "y"
                configure.write_config(self.config, values)
                with self.assertRaisesRegex(ValueError, "Unexpected device"):
                    configure.verify(self.config, self.required)

    def test_required_exclusions_cannot_be_reenabled(self):
        self.prepare()
        values = configure.read_config(self.config)
        values["CONFIG_TARGET_ALL_PROFILES"] = "y"
        values["CONFIG_PACKAGE_tcpdump"] = "y"
        configure.write_config(self.config, values)
        with self.assertRaises(ValueError) as caught:
            configure.verify(self.config, self.required)
        self.assertIn("CONFIG_TARGET_ALL_PROFILES=n", str(caught.exception))
        self.assertIn("CONFIG_PACKAGE_tcpdump=n", str(caught.exception))

    def test_group_without_wxr_fails(self):
        self.group.write_text("CONFIG_TARGET_qualcommax_ipq807x=y\n")
        with self.assertRaisesRegex(ValueError, "must include"):
            self.prepare()

    def test_explicit_tcpdump_disables_mini(self):
        self.packages.write_text("tcpdump=m\n")
        self.prepare()
        values = configure.read_config(self.config)
        self.assertEqual(values["CONFIG_PACKAGE_tcpdump"], "m")
        self.assertEqual(values["CONFIG_PACKAGE_tcpdump-mini"], "n")


if __name__ == "__main__":
    unittest.main()
