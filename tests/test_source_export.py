"""Source-only publication checks; no Blender, models or voice fixtures needed."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('source_export', ROOT / 'scripts/export_source.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@unittest.skipUnless(shutil.which('git'), 'git is required')
class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'source repo'
        self.root.mkdir()
        subprocess.run(['git', 'init', '--quiet'], cwd=self.root, check=True)
        shutil.copy2(ROOT / '.gitignore', self.root / '.gitignore')

    def write(self, name, text='local data'):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')

    def test_export_excludes_assets_even_when_previously_tracked(self):
        kept = ['README.md', 'module.py', 'new_source.py', 'pipeline.example.json',
                'tests/test_example.py', 'docs/assets/diagram.png',
                '.agents/skills/example/SKILL.md']
        ignored = ['rigged.blend', 'models/HEAD.FBX', 'work/run/report.json',
                   'scratchpad/debug.py', 'test_subjects/models/source.glb',
                   'pipeline.local.json', '.env', 'voice.WAV', 'preview.png',
                   'dist/addon.zip', 'experiments/local_test.py']
        for name in kept + ignored:
            self.write(name)
        subprocess.run(['git', 'add', '-f', '--', 'rigged.blend', 'module.py'],
                       cwd=self.root, check=True)
        destination = Path(self.temp.name) / 'public source'
        files = module.export(self.root, destination, initialize=True)
        self.assertTrue(set(kept).issubset(files))
        self.assertFalse(set(ignored).intersection(files))
        self.assertTrue((self.root / 'rigged.blend').exists())
        self.assertTrue((destination / '.git').is_dir())
        self.assertEqual(subprocess.check_output(['git', 'remote'], cwd=destination), b'')
        self.assertNotEqual(subprocess.run(['git', 'rev-parse', '--verify', 'HEAD'],
                                          cwd=destination, capture_output=True).returncode, 0)

    def test_refuses_existing_nonempty_destination(self):
        self.write('module.py')
        destination = Path(self.temp.name) / 'existing'
        destination.mkdir()
        sentinel = destination / 'keep.txt'
        sentinel.write_text('keep')
        with self.assertRaises(ValueError):
            module.export(self.root, destination)
        self.assertEqual(sentinel.read_text(), 'keep')

    def test_refuses_export_over_source_or_ancestor(self):
        for destination in [self.root, self.root.parent]:
            with self.assertRaises(ValueError):
                module.export(self.root, destination)

    def test_missing_tracked_files_are_not_resurrected(self):
        self.write('removed.py')
        self.write('retained.py')
        subprocess.run(['git', 'add', '--', 'removed.py'], cwd=self.root, check=True)
        (self.root / 'removed.py').unlink()
        files = module.export(self.root, Path(self.temp.name) / 'export')
        self.assertNotIn('removed.py', files)
        self.assertIn('retained.py', files)


if __name__ == '__main__':
    unittest.main()
