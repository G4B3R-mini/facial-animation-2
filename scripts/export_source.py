"""Export current non-ignored source without assets or Git history.

python scripts/export_source.py scratchpad/public-release --init
"""
import argparse
from pathlib import Path
import shutil
import subprocess


def source_files(root):
    listing = subprocess.check_output(
        ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=root)
    paths = sorted(set(p.decode('utf-8') for p in listing.split(b'\0') if p))
    if not paths:
        return []
    ignored = subprocess.run(
        ['git', 'check-ignore', '--no-index', '-z', '--stdin'], cwd=root,
        input=('\0'.join(paths) + '\0').encode('utf-8'), stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)
    if ignored.returncode not in (0, 1):
        raise RuntimeError(ignored.stderr.decode('utf-8', errors='replace'))
    excluded = set(p.decode('utf-8') for p in ignored.stdout.split(b'\0') if p)
    return [p for p in paths if p not in excluded and (root / p).is_file()]


def export(root, destination, initialize=False):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    if destination == root or destination in root.parents:
        raise ValueError('Destination must not be the source repository or its ancestor')
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError('Destination must be a new or empty directory')
    paths = source_files(root)
    if not paths:
        raise ValueError('No source files to export')
    # A linked source file might point outside the clone; preserve no such links.
    for relative in paths:
        source = root / relative
        if source.is_symlink() or root not in source.resolve().parents:
            raise ValueError('Export requires ordinary files inside the clone: ' + relative)
    destination.mkdir(parents=True, exist_ok=True)
    for relative in paths:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, target)
    if initialize:
        subprocess.run(['git', 'init', '--initial-branch=main'], cwd=destination, check=True)
        subprocess.run(['git', 'add', '--all'], cwd=destination, check=True)
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--init', action='store_true', help='Initialize and stage a new main branch; no commit/push')
    args = parser.parse_args()
    paths = export(Path(__file__).resolve().parents[1], args.destination, args.init)
    print('Exported %d source files to %s' % (len(paths), args.destination.resolve()))


if __name__ == '__main__':
    main()
