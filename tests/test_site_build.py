import tempfile
import unittest
from pathlib import Path

from xsite import build_site


class SiteBuildTests(unittest.TestCase):
    def test_versions_entry_points_and_nested_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "site"
            output = Path(directory) / "output"
            source.mkdir()
            fixtures = {
                "index.html": '<script src="app.mjs"></script><link href="style.css">',
                "app.mjs": "import './editors.mjs'; new Worker('./worker.mjs');",
                "editors.mjs": "await import('./color.js');",
                "worker.mjs": "fetch('./bridge.py'); fetch('https://example.org/runtime.js');",
                "color.js": "// editor",
                "bridge.py": "# adapter",
                "style.css": "/* style */",
            }
            for name, text in fixtures.items():
                (source / name).write_text(text, encoding="utf-8")
            version = build_site(source, output)
            for name, targets in {
                "index.html": ["app.mjs", "style.css"],
                "app.mjs": ["./editors.mjs", "./worker.mjs"],
                "editors.mjs": ["./color.js"],
                "worker.mjs": ["./bridge.py"],
            }.items():
                for target in targets:
                    self.assertIn(f"{target}?v={version}", (output / name).read_text())
            self.assertIn("'https://example.org/runtime.js'", (output / "worker.mjs").read_text())
            self.assertEqual(version, build_site(source, output))
            (source / "editors.mjs").write_text("// changed", encoding="utf-8")
            self.assertNotEqual(version, build_site(source, output))
            self.assertEqual((source / "index.html").read_text(), fixtures["index.html"])
