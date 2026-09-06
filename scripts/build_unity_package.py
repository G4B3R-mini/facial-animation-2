"""Build a source-only Unity import package: python scripts/build_unity_package.py.

Stable metadata preserves references when upgrading the reference project's scripts.
No Unity installation, character assets, audio or external binaries are required.
"""
import io
import tarfile
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ['ConversationalGaze', 'ConversationExpressionDriver', 'FaceMeshUtil',
           'RhubarbVisemePlayer', 'SpeechAnalysis', 'SpeechGestureDriver',
           'SpeechPerformanceProfile', 'SubtleBodyDriver', 'RuntimeLipSyncService']
EDITOR = ['CharacterPipelineSetup', 'CharacterRhubarb']


def package_files():
    for name in RUNTIME + EDITOR:
        source = ROOT / 'unity' / ('Editor' if name in EDITOR else '') / (name + '.cs')
        destination = ('Assets/Editor/TripoFaceRig/' if name in EDITOR else 'Assets/Scripts/TripoFaceRig/') + name + '.cs'
        yield source, destination


def build(destination=None):
    destination = Path(destination or ROOT / 'dist/TripoFaceRig-Unity.unitypackage')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(destination, 'w:gz', format=tarfile.USTAR_FORMAT) as archive:
        for source, target in package_files():
            meta = Path(str(source) + '.meta').read_bytes()
            guid = re.search(rb'^guid: ([0-9a-f]{32})$', meta, re.M).group(1).decode()
            for name, data in [('asset', source.read_bytes()), ('asset.meta', meta), ('pathname', target.encode())]:
                info = tarfile.TarInfo(guid + '/' + name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
    return destination


if __name__ == '__main__':
    print(build())
