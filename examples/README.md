# Example assets

`blacksmith_teeth.blend` is a prepared-head example for the first pipeline
stage. It contains these artist-positioned objects:

- `tripo_node_b5ad4dee`: head mesh
- `upper_jaw`: upper teeth
- `lower_jaw`: lower teeth
- `tongue`: tongue mesh

The textures are packed into the Blender file, so it has no external file-path
dependency. Copy the file into an ignored `work/` directory before experimenting:

```powershell
Copy-Item examples/blacksmith_teeth.blend work/blacksmith/source.blend
.\rig.ps1 work/blacksmith/source.blend -Object tripo_node_b5ad4dee `
  -Teeth upper_jaw,lower_jaw -Tongue tongue
```

The example demonstrates part placement and naming. It is not a universal
anatomical template, and an agent should still audit the scene before rigging.
The file is provided under the repository's MIT License.
