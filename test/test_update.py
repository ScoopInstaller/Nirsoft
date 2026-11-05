"""Offline regression tests for generated persistent configuration files.

Run with: python -m unittest discover -s test -p "test_*.py"
"""

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import update


class PersistTests(unittest.TestCase):
    def generate(self, name="pinginfoview", x64=False):
        pad = f"""<XML_DIZ_INFO>
            <Program_Info><Program_Version>3.25</Program_Version>
                <Program_Name>{name}</Program_Name></Program_Info>
            <Web_Info>
                <Application_URLs><Application_Info_URL>https://www.nirsoft.net/</Application_Info_URL></Application_URLs>
                <Download_URLs><Primary_Download_URL>https://www.nirsoft.net/utils/{name}.zip</Primary_Download_URL></Download_URLs>
            </Web_Info>
        </XML_DIZ_INFO>"""
        row = {"exe": f"{name}.exe", "hash": "0" * 64}
        original_dir = os.getcwd()
        with tempfile.TemporaryDirectory() as temporary_dir:
            try:
                os.chdir(temporary_dir)
                Path("bucket").mkdir()
                with patch.object(update, "update_row", side_effect=[(True, row), (x64, row)]):
                    with contextlib.redirect_stdout(io.StringIO()):
                        update.do_padfile(f"{name}.xml", pad, {})
                return json.loads(Path(f"bucket/{name}.json").read_text(encoding="utf-8"))
            finally:
                os.chdir(original_dir)

    def test_pinginfoview_has_file_initialization(self):
        manifest = self.generate()
        self.assertEqual(len(manifest["pre_install"]), 2)
        for filename, command in zip(manifest["persist"], manifest["pre_install"]):
            self.assertIn(filename, command)
            self.assertIn("-ItemType File", command)

    def test_password_archive_is_extracted_before_initialization(self):
        for x64 in (False, True):
            with self.subTest(x64=x64):
                manifest = self.generate("netpass", x64=x64)
                self.assertEqual(len(manifest["pre_install"]), 4)
                self.assertIn("7z x", manifest["pre_install"][1])
                self.assertTrue(all("-ItemType File" in line for line in manifest["pre_install"][2:]))
                urls = ([arch["url"] for arch in manifest["architecture"].values()]
                        if x64 else [manifest["url"]])
                self.assertTrue(all(url.endswith("#dl.zip_") for url in urls))

    @unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Requires PowerShell on Windows")
    def test_hooks_create_files_and_preserve_existing_configuration(self):
        hooks = "\n".join(self.generate()["pre_install"])
        for existing in ("none", "source", "persist", "directory"):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as temporary_dir:
                root = Path(temporary_dir)
                source = root / "app"
                persistent = root / "persist"
                source.mkdir()
                persistent.mkdir()
                cfg = "pinginfoview.cfg"
                content = b"[General]\r\nSort=14\r\n"
                if existing in ("source", "persist"):
                    (source if existing == "source" else persistent).joinpath(cfg).write_bytes(content)
                elif existing == "directory":
                    (persistent / cfg).mkdir()
                    (persistent / cfg / "keep.txt").write_bytes(content)
                script = root / "hooks.ps1"
                script.write_text(
                    'param($dir, $persist_dir)\n$ErrorActionPreference = "Stop"\n' + hooks,
                    encoding="utf-8",
                )
                # Running twice also checks that reinstallation is safe.
                for _ in range(2):
                    subprocess.run(
                        ["pwsh", "-NoProfile", "-File", str(script), str(source), str(persistent)],
                        check=True, capture_output=True, text=True,
                    )
                self.assertTrue((source / "pinginfoview_lng.ini").is_file())
                if existing == "none":
                    self.assertTrue((source / cfg).is_file())
                elif existing == "source":
                    self.assertEqual((source / cfg).read_bytes(), content)
                else:
                    self.assertFalse((source / cfg).exists())
                    if existing == "persist":
                        self.assertEqual((persistent / cfg).read_bytes(), content)
                    else:
                        self.assertEqual((persistent / cfg / "keep.txt").read_bytes(), content)


if __name__ == "__main__":
    unittest.main()
