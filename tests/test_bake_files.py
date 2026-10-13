import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bake_files", ROOT / "scripts/bake_files.py")
bake_files = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bake_files)


class BakeFilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.output = self.root / "files"
        self.map = self.root / "map.txt"
        self.map.write_text("# comment\nscript /usr/sbin/script 0755\nlib.sh /usr/lib/lib.sh 0644\n")
        (self.source / "script").write_text("#!/bin/sh\necho safe\n")
        (self.source / "lib.sh").write_text("# safe\n")

    def test_map_and_sync(self):
        entries = bake_files.read_map(self.map)
        self.assertEqual(len(entries), 2)
        bake_files.sync(self.source, self.map, self.output)
        self.assertEqual((self.output / "usr/sbin/script").stat().st_mode & 0o777, 0o755)
        self.assertEqual((self.output / "usr/lib/lib.sh").stat().st_mode & 0o777, 0o644)
        self.assertEqual((self.output / "etc/wxr5950-baked-paths").read_text().splitlines(), [
            "/etc/uci-defaults/90-wxr5950-bake", "/etc/wxr5950-baked-paths",
            "/usr/lib/lib.sh", "/usr/sbin/script",
        ])

    def test_secret_scan_rejects_and_preserves_previous_output(self):
        bake_files.sync(self.source, self.map, self.output)
        original = (self.output / "usr/sbin/script").read_bytes()
        for content in ("person@example.invalid\n", "-----BEGIN PRIVATE KEY-----\n",
                        "https://ntfy.sh/longtopic123456\n", "Aa0123456789" * 5):
            with self.subTest(content=content[:12]):
                (self.source / "script").write_text(content)
                with self.assertRaisesRegex(ValueError, "Secret"):
                    bake_files.sync(self.source, self.map, self.output)
                self.assertEqual((self.output / "usr/sbin/script").read_bytes(), original)

    def test_sync_shell_entry_point_rejects_secret(self):
        command = [str(ROOT / "scripts/sync-router-files.sh"), str(self.source),
                   "--map", str(self.map), "--output", str(self.output)]
        normal = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(normal.returncode, 0, normal.stderr)
        (self.source / "script").write_text("-----BEGIN PRIVATE KEY-----\n")
        rejected = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("Secret", rejected.stderr)
        self.assertEqual((self.output / "usr/sbin/script").read_text(), "#!/bin/sh\necho safe\n")

    def test_map_rejects_traversal_and_duplicate(self):
        for line in ("x /usr/../etc/x 0755", "x /usr/sbin/script 0755",
                     "../x /usr/bin/x 0755", "x /usr/bin/x 07777"):
            with self.subTest(line=line):
                self.map.write_text("script /usr/sbin/script 0755\n" + line + "\n")
                with self.assertRaises(ValueError):
                    bake_files.read_map(self.map)

    def test_rootfs_verification(self):
        bake_files.sync(self.source, self.map, self.output)
        missing_hashes = self.root / "missing-root.sha256"
        bake_files.verify_rootfs(self.output, self.root / "absent-build-dir", missing_hashes)
        self.assertEqual(len(missing_hashes.read_text().splitlines()), 4)
        root = self.root / "build_dir/target-test/root-test"
        root.mkdir(parents=True)
        import shutil
        shutil.copytree(self.output, root, dirs_exist_ok=True)
        bake_files.verify_rootfs(self.output, self.root / "build_dir", self.root / "baked.sha256")
        (root / "usr/sbin/script").write_text("changed")
        with self.assertRaisesRegex(ValueError, "mismatched"):
            bake_files.verify_rootfs(self.output, self.root / "build_dir", self.root / "baked.sha256")

    def test_overlay_copy_preserves_modes_and_rejects_collision(self):
        source = self.root / "overlay-source"
        target = self.root / "overlay-target"
        (source / "etc/uci-defaults").mkdir(parents=True)
        (target / "etc/uci-defaults").mkdir(parents=True)
        own = source / "etc/uci-defaults/90-wxr5950-bake"
        own.write_text("new\n")
        own.chmod(0o755)
        command = ["bash", str(ROOT / "scripts/overlay-files.sh"), str(source), str(target)]
        copied = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(copied.returncode, 0, copied.stderr)
        self.assertEqual((target / "etc/uci-defaults/90-wxr5950-bake").stat().st_mode & 0o777, 0o755)
        own.write_text("replacement\n")
        collision = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(collision.returncode, 0)
        self.assertIn("collision", collision.stderr)
        self.assertEqual((target / "etc/uci-defaults/90-wxr5950-bake").read_text(), "new\n")
