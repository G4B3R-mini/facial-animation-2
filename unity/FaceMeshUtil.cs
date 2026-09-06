using System.Collections.Generic;
using UnityEngine;

namespace TripoFaceRig
{
    /// <summary>
    /// Finds the mesh whose blendshapes actually move the face.
    ///
    /// Vertex count is NOT a safe discriminator and has now caused the same bug
    /// twice, in Blender and again in C#. Separating hair by loose parts copies
    /// every shape key onto both halves, so on this character the hair carries
    /// all 72 shapes at 2987 verts against the head's 2503 - "densest mesh with
    /// vrc.v_aa" therefore picks the HAIR, whose copies are inert. uLipSync then
    /// drives shapes that deform nothing and the mouth never moves.
    ///
    /// Test what the shape does, not how big the mesh is.
    /// </summary>
    public static class FaceMeshUtil
    {
        /// <summary>
        /// The renderer whose named blendshape has the largest actual vertex
        /// displacement. Returns null if no mesh carries the shape with real data.
        /// </summary>
        public static SkinnedMeshRenderer FindDeformingRenderer(GameObject root, string shapeName)
        {
            SkinnedMeshRenderer best = null;
            float bestDelta = 0f;

            foreach (var smr in root.GetComponentsInChildren<SkinnedMeshRenderer>(true))
            {
                var mesh = smr.sharedMesh;
                if (mesh == null) continue;
                int idx = mesh.GetBlendShapeIndex(shapeName);
                if (idx < 0) continue;

                float delta = MaxDelta(mesh, idx);
                if (delta > bestDelta)
                {
                    bestDelta = delta;
                    best = smr;
                }
            }
            return bestDelta > 1e-6f ? best : null;
        }

        /// <summary>
        /// Every renderer whose named shape actually deforms. browInnerUp lives on
        /// the head ridge AND on both separated brow objects, so driving only one
        /// renderer moves a third of the brow.
        /// </summary>
        public static List<SkinnedMeshRenderer> FindAllDeforming(GameObject root, string shapeName)
        {
            var found = new List<SkinnedMeshRenderer>();
            foreach (var smr in root.GetComponentsInChildren<SkinnedMeshRenderer>(true))
            {
                var mesh = smr.sharedMesh;
                if (mesh == null) continue;
                int idx = mesh.GetBlendShapeIndex(shapeName);
                if (idx < 0) continue;
                if (MaxDelta(mesh, idx) > 1e-6f) found.Add(smr);
            }
            return found;
        }

        /// <summary>Union of actual deformations, including channels on separate meshes such as the tongue.</summary>
        public static List<SkinnedMeshRenderer> FindAllDeforming(GameObject root, string[] shapes)
        {
            var found = new List<SkinnedMeshRenderer>();
            foreach (var renderer in root.GetComponentsInChildren<SkinnedMeshRenderer>(true))
            {
                var mesh = renderer.sharedMesh;
                if (mesh == null) continue;
                foreach (string shape in shapes)
                {
                    int index = mesh.GetBlendShapeIndex(shape);
                    if (index < 0 || MaxDelta(mesh, index) <= 1e-6f) continue;
                    found.Add(renderer);
                    break;
                }
            }
            return found;
        }

        public static bool Deforms(Mesh mesh, int shapeIndex) =>
            mesh != null && shapeIndex >= 0 && shapeIndex < mesh.blendShapeCount && MaxDelta(mesh, shapeIndex) > 1e-6f;

        private static float MaxDelta(Mesh mesh, int shapeIndex)
        {
            int frames = mesh.GetBlendShapeFrameCount(shapeIndex);
            if (frames <= 0) return 0f;

            var dv = new Vector3[mesh.vertexCount];
            mesh.GetBlendShapeFrameVertices(shapeIndex, frames - 1, dv, null, null);

            float max = 0f;
            for (int i = 0; i < dv.Length; i++)
            {
                float m = dv[i].sqrMagnitude;
                if (m > max) max = m;
            }
            return Mathf.Sqrt(max);
        }
    }
}
