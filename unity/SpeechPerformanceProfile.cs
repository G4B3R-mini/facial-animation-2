using System;
using UnityEngine;

namespace TripoFaceRig
{
    public enum ConversationMood { Attentive, Warm, Thinking, Concern, Emphasis }

    /// <summary>Reusable gesture segments and optional acting notes for a reference recording.</summary>
    [CreateAssetMenu(menuName = "Tripo Face Rig/Speech Performance Profile")]
    public sealed class SpeechPerformanceProfile : ScriptableObject
    {
        [Serializable]
        public struct GestureSegment
        {
            public string name;
            public AnimationClip clip;
            public string stateName;
            [Min(0f)] public float start;
            [Min(0f)] public float accent;
            [Min(0f)] public float holdUntil;
            [Min(0f)] public float end;

            public bool IsValid => clip != null && !string.IsNullOrEmpty(stateName) &&
                start >= 0f && accent > start && holdUntil >= accent &&
                end > holdUntil && end <= clip.length + 0.001f;

            public float WeightAt(float sourceTime)
            {
                if (!IsValid || sourceTime <= start || sourceTime >= end) return 0f;
                float up = Mathf.SmoothStep(0f, 1f, Mathf.InverseLerp(start, accent, sourceTime));
                float down = 1f - Mathf.SmoothStep(0f, 1f, Mathf.InverseLerp(holdUntil, end, sourceTime));
                return up * down;
            }
        }

        [Serializable]
        public struct GestureCue
        {
            [Min(0f)] public float accentTime;
            [Min(0)] public int segment;
            [Range(0f, 1f)] public float strength;
        }

        [Serializable]
        public struct ExpressionCue
        {
            [Min(0f)] public float time;
            [Min(0.1f)] public float duration;
            public ConversationMood mood;
            [Range(0f, 1f)] public float strength;
        }

        public int randomSeed = 731;
        [Min(1f)] public float minimumGestureGap = 3.2f;
        public GestureSegment[] gestures = Array.Empty<GestureSegment>();
        [Tooltip("Acting notes below apply only to this exact clip. Other clips use audio analysis.")]
        public AudioClip referenceClip;
        public GestureCue[] referenceGestures = Array.Empty<GestureCue>();
        public ExpressionCue[] referenceExpressions = Array.Empty<ExpressionCue>();
    }
}
