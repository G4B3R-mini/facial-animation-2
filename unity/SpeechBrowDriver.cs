using UnityEngine;

namespace TripoFaceRig
{
    /// <summary>
    /// Raises the brows with speech loudness at runtime.
    ///
    /// The baked face clip used to carry brow motion derived from one specific
    /// waveform in Blender. That cannot work for generated dialogue, so the
    /// ambient clip now holds only blinks, gaze and a little idle brow drift on
    /// the brow BONES, while this drives the browInnerUp BLENDSHAPE from live
    /// audio. Bones and blendshape are separate channels, so the two add rather
    /// than fight.
    ///
    /// Measured on this character: browInnerUp at full weight displaces the brow
    /// objects 0.0088 against 0.0066 for the bones, so the blendshape alone can
    /// carry the performance - which also makes it survive Humanoid retargeting,
    /// where brow bones have no slot.
    ///
    /// LateUpdate on purpose: the Animator writes blendshapes during its own
    /// update, so anything set earlier is overwritten.
    /// </summary>
    public sealed class SpeechBrowDriver : MonoBehaviour
    {
        [SerializeField] private SpeechGestureDriver speech;
        [SerializeField] private SkinnedMeshRenderer[] targets;

        [Tooltip("Blendshape raised with speech loudness.")]
        [SerializeField] private string shapeName = "browInnerUp";

        [Tooltip("Weight at full loudness, 0..1. Above ~0.7 reads as permanent surprise.")]
        [Range(0f, 1f)] [SerializeField] private float maxWeight = 0.55f;

        [Tooltip("Loudness below this contributes nothing, so quiet passages sit at rest.")]
        [Range(0f, 1f)] [SerializeField] private float threshold = 0.25f;

        [Tooltip("Seconds to follow the level. Brows are slow; too fast reads as twitchy.")]
        [SerializeField] private float smoothing = 0.10f;

        private int[] indices;
        private float current;

        private void Reset()
        {
            speech = GetComponent<SpeechGestureDriver>();
        }

        private void Awake()
        {
            if (speech == null) speech = GetComponent<SpeechGestureDriver>();
            if (targets == null || targets.Length == 0)
                targets = FaceMeshUtil.FindAllDeforming(gameObject, shapeName).ToArray();

            indices = new int[targets.Length];
            for (int i = 0; i < targets.Length; i++)
                indices[i] = targets[i] != null && targets[i].sharedMesh != null
                    ? targets[i].sharedMesh.GetBlendShapeIndex(shapeName) : -1;

            if (targets.Length == 0)
                Debug.LogWarning($"[TripoFaceRig] No mesh deforms with '{shapeName}'; " +
                                 "brows will not react.", this);
        }

        private void LateUpdate()
        {
            if (targets == null || targets.Length == 0) return;

            float level = (speech != null && speech.IsSpeaking) ? speech.Level : 0f;
            float lift = Mathf.Clamp01((level - threshold) / Mathf.Max(0.01f, 1f - threshold));
            lift = Mathf.Pow(lift, 1.3f) * maxWeight;

            current = Mathf.Lerp(current, lift,
                1f - Mathf.Exp(-Time.deltaTime / Mathf.Max(0.01f, smoothing)));

            // Straight assignment is safe: the ambient clip animates the brow
            // BONES, and carries no curve for this blendshape (verified on export
            // - Armature|Scene holds 20 brow bone curves, the shape-key action
            // holds only the two blinks).
            float w = Mathf.Clamp(current * 100f, 0f, 100f);
            for (int i = 0; i < targets.Length; i++)
                if (targets[i] != null && indices[i] >= 0)
                    targets[i].SetBlendShapeWeight(indices[i], w);
        }
    }
}
