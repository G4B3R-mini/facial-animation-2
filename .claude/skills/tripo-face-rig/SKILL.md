---
name: tripo-face-rig
description: Guide a prepared head through rigging, a speaking Blender preview, manual body attachment, skeleton merging, FBX export, and Unity scene setup using the shared pipeline.
---

# Tripo face rig

Read [the shared skill instructions](../../../.agents/skills/tripo-face-rig/SKILL.md)
and follow them for source audit, artist preparation, build, diagnosis, targeted
repair, visual review, a sample-audio Blender test, and the body/Unity handoff.

The repository root is three directories above this skill directory. The maintained
implementations live in `scripts/face_pipeline/`; the scripts under this skill
are compatibility entrypoints for earlier commands.

Shared documentation:
- [Workflow](../../../docs/workflow.md)
- [Troubleshooting](../../../docs/troubleshooting.md)
- [Diagnostics and optional repairs](../../../docs/diagnostics.md)

Use the user's existing authorization and accepted model/rig. Do not restart
manual setup or demand another approval for already accepted preparation.
