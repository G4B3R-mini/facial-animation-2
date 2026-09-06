import importlib.util
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_unity_package', ROOT / 'scripts/build_unity_package.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class UnityPackageTests(unittest.TestCase):
    def test_import_paths_guids_and_exact_source(self):
        with tempfile.TemporaryDirectory() as folder:
            package = builder.build(Path(folder) / 'test.unitypackage')
            with tarfile.open(package) as archive:
                paths = [m for m in archive.getmembers() if m.name.endswith('/pathname')]
                self.assertEqual(len(paths), 11)
                self.assertEqual(len({m.name.split('/')[0] for m in paths}), 11)
                actual = {}
                for member in paths:
                    guid = member.name.split('/')[0]
                    target = archive.extractfile(member).read().decode()
                    self.assertTrue(target.startswith('Assets/'))
                    self.assertNotIn('..', target)
                    meta = archive.extractfile(guid + '/asset.meta').read()
                    self.assertIn(('guid: ' + guid).encode(), meta)
                    actual[target] = archive.extractfile(guid + '/asset').read()
                for source, target in builder.package_files():
                    self.assertEqual(source.read_bytes(), actual[target])
                self.assertTrue(any('CharacterPipelineSetup.cs' in p for p in actual))


if __name__ == '__main__':
    unittest.main()
