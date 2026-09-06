using System;
using System.Collections.Generic;
using UnityEngine;

namespace TripoFaceRig
{
    /// <summary>
    /// Routes normalized ARKit or VRChat coefficients to every configured
    /// SkinnedMeshRenderer. Include the separate tongue renderer so tongueOut
    /// is found automatically. This component deliberately does not own audio,
    /// tracking, or dialogue timing; those systems call SetExpression.
    /// </summary>
    public sealed class TripoFaceExpressionDriver : MonoBehaviour
    {
        [Serializable]
        public struct Coefficient
        {
            public string name;
            [Range(0f, 1f)] public float value;
        }

        [SerializeField] private SkinnedMeshRenderer[] renderers;
        [SerializeField] private bool captureImportedNeutral = true;
        [SerializeField] private Coefficient[] editorPreview;

        private readonly Dictionary<string, List<ShapeTarget>> targets =
            new Dictionary<string, List<ShapeTarget>>(StringComparer.Ordinal);
        private readonly Dictionary<ShapeTargetId, float> neutralWeights =
            new Dictionary<ShapeTargetId, float>();

        private readonly struct ShapeTarget
        {
            public readonly SkinnedMeshRenderer renderer;
            public readonly int index;

            public ShapeTarget(SkinnedMeshRenderer renderer, int index)
            {
                this.renderer = renderer;
                this.index = index;
            }
        }

        private readonly struct ShapeTargetId : IEquatable<ShapeTargetId>
        {
            private readonly int rendererId;
            private readonly int index;

            public ShapeTargetId(SkinnedMeshRenderer renderer, int index)
            {
                rendererId = renderer.GetInstanceID();
                this.index = index;
            }

            public bool Equals(ShapeTargetId other) =>
                rendererId == other.rendererId && index == other.index;
            public override bool Equals(object obj) =>
                obj is ShapeTargetId other && Equals(other);
            public override int GetHashCode() => (rendererId * 397) ^ index;
        }

        private void Awake()
        {
            RebuildCache();
        }

        public void RebuildCache()
        {
            targets.Clear();
            neutralWeights.Clear();
            if (renderers == null)
                return;

            foreach (var renderer in renderers)
            {
                if (renderer == null || renderer.sharedMesh == null)
                    continue;
                for (var index = 0; index < renderer.sharedMesh.blendShapeCount; index++)
                {
                    var importedName = renderer.sharedMesh.GetBlendShapeName(index);
                    Register(importedName, renderer, index);

                    // Some FBX importers prefix keys with the mesh name.
                    var dot = importedName.LastIndexOf('.');
                    if (dot >= 0 && dot + 1 < importedName.Length)
                        Register(importedName.Substring(dot + 1), renderer, index);

                    var id = new ShapeTargetId(renderer, index);
                    neutralWeights[id] = captureImportedNeutral
                        ? renderer.GetBlendShapeWeight(index)
                        : 0f;
                }
            }
        }

        private void Register(string name, SkinnedMeshRenderer renderer, int index)
        {
            if (!targets.TryGetValue(name, out var list))
            {
                list = new List<ShapeTarget>();
                targets.Add(name, list);
            }
            list.Add(new ShapeTarget(renderer, index));
        }

        /// <summary>Set a 0..1 ARKit expression or a vrc.v_* viseme.</summary>
        public bool SetExpression(string name, float value)
        {
            if (!targets.TryGetValue(name, out var matches))
                return false;

            value = Mathf.Clamp01(value);
            foreach (var target in matches)
            {
                var id = new ShapeTargetId(target.renderer, target.index);
                var neutral = neutralWeights.TryGetValue(id, out var saved) ? saved : 0f;
                target.renderer.SetBlendShapeWeight(
                    target.index, Mathf.Clamp(neutral + value * 100f, 0f, 100f));
            }
            return true;
        }

        /// <summary>Apply a complete frame, clearing coefficients omitted from it.</summary>
        public void ApplyFrame(IEnumerable<Coefficient> frame)
        {
            ResetToImportedNeutral();
            foreach (var coefficient in frame)
                SetExpression(coefficient.name, coefficient.value);
        }

        public void ResetToImportedNeutral()
        {
            foreach (var pair in targets)
            foreach (var target in pair.Value)
            {
                var id = new ShapeTargetId(target.renderer, target.index);
                if (neutralWeights.TryGetValue(id, out var weight))
                    target.renderer.SetBlendShapeWeight(target.index, weight);
            }
        }

        [ContextMenu("Apply Editor Preview")]
        private void ApplyEditorPreview()
        {
            if (targets.Count == 0)
                RebuildCache();
            ResetToImportedNeutral();
            ApplyFrame(editorPreview);
        }
    }
}
