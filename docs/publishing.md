# Preparing a public source repository

Build the installable Unity release with `python scripts/build_unity_package.py`.
Attach `dist/TripoFaceRig-Unity.unitypackage` to the GitHub release. It contains
maintained C# source and stable Unity metadata, with no model, voice, motion clips,
Rhubarb executable or project scene. `dist/` stays ignored; the builder and source
remain in Git. The Unity guide explains installation and the setup window.
The included **Build Unity package** GitHub Actions workflow also builds a
downloadable artifact on demand and attaches it automatically to published
GitHub releases.

The root `.gitignore` excludes working directories, models, generated media,
Rhubarb reports, packaged binaries, downloaded dependencies, local configuration
and personal experiment/history files. Keep new runs under `work/` so their JSON
reports and other output are excluded too. Source tests in `tests/`, manifests,
example configuration, and deliberately authored `docs/assets/` remain trackable.

Ignoring a file does not remove it from the index or from earlier commits.
For an artifact already tracked, use `git rm --cached -- path` to stop tracking
it while retaining the local copy. Inspect `git status`, `git diff --cached`,
and `git ls-files` before committing. Do not use filesystem deletion to clean
the Git index.

## Start public history from a clean export

This development checkout has older commits containing model/test artifacts.
Pushing its existing branch transfers those historical objects even after the
current tree has been cleaned. The source exporter creates a separate directory
from the **current working source**, applying `.gitignore` even to tracked files.
It does not copy `.git`, user assets, machine configuration, or old history.

```powershell
python scripts/export_source.py scratchpad/public-release --init
```

The destination must be new or empty; the exporter never deletes an existing
directory. `--init` initializes a new `main` branch and stages the exported
source, but makes no commit and contacts no remote. Review it before publishing:

```powershell
Set-Location scratchpad/public-release
git status --short
git diff --cached --stat
```

The repository is distributed under the root MIT License. Confirm that any new
example assets are owned by the contributor or have compatible redistribution
terms. Then commit and add the GitHub remote in this **exported repository**.
No remote URL, commit, push, or history rewrite is performed by preparation.
If you instead need to retain existing public history, review a separate history
cleanup/migration; do not force-push rewritten history as an incidental cleanup.

The exporter includes non-ignored new source files as well as tracked working
files, so review that list. Ignoring common credentials is not a complete secret
scan. Keep confidential content out of tracked code/docs and review provenance
before publication. External assets are not covered by any future code license.
