# External tools and assets

The maintained Blender pipeline uses your installed Blender and Rhubarb; their
executables are not vendored here. Models, voice clips, generated rigs,
packaged extensions, and downloaded reference assets are excluded from the
public source tree, except for the repository-owned Blacksmith prepared-head
example documented under `examples/`.

- [Blender](https://www.blender.org/): runs the `bpy` scripts. Review Blender's
  own distribution license if redistributing Blender itself.
- [Rhubarb Lip Sync](https://github.com/DanielSWolf/rhubarb-lip-sync): generates
  speech cues; retain the full distribution and its notices when redistributing.
- [Pillow](https://python-pillow.org/): optional dependency of the contact-sheet
  helper in regular Python, not Blender's embedded Python.
- Legacy canonical modules reference [ICT-FaceKit](https://github.com/ICT-VGL/ICT-FaceKit).
  Its assets and generated canonical blend are not shipped here. Those modules
  are outside the maintained quick start; obtain upstream resources and review
  their license/requirements separately if using them.
- `unity/` contains Unity integration source. The maintained installer selects
  components using Unity built-ins; legacy scripts may need additional packages.
  Body animation clips and the Unity editor are not bundled.

Your model-generation service, donor teeth, texture sources, voice recordings,
and motion clips may have separate usage terms. A repository code license does
not relicense any of those assets. Local working assets are not licensed for
redistribution merely because they exist beside this repository. The included
`examples/blacksmith_teeth.blend` file is an explicit exception and is covered
by the repository's MIT License.
