using UnityEngine;

namespace TripoFaceRig
{
    /// <summary>Final owner of expression channels. Mixes speech smile coefficients once, after lipsync.</summary>
    [DefaultExecutionOrder(300)]
    public sealed class ConversationExpressionDriver : MonoBehaviour
    {
        [SerializeField] private SpeechGestureDriver speech;
        [SerializeField] private RhubarbVisemePlayer mouth;
        [SerializeField] private ConversationalGaze gaze;
        [SerializeField, Range(0f, 1f)] private float strength = 0.65f;
        [SerializeField, Min(0.05f)] private float smoothing = 0.22f;

        private static readonly string[] Shapes =
        {
            "browInnerUp", "browOuterUpLeft", "browOuterUpRight", "browDownLeft", "browDownRight",
            "eyeSquintLeft", "eyeSquintRight", "cheekSquintLeft", "cheekSquintRight",
            "mouthSmileLeft", "mouthSmileRight"
        };
        private SkinnedMeshRenderer[] targets;
        private int[][] indices;
        private readonly float[] current = new float[11];
        private readonly float[] desired = new float[11];
        private int lastLine = -1;

        private void Awake()
        {
            if (speech == null) speech = GetComponent<SpeechGestureDriver>();
            if (mouth == null) mouth = GetComponent<RhubarbVisemePlayer>();
            if (gaze == null) gaze = GetComponent<ConversationalGaze>();
            targets = FaceMeshUtil.FindAllDeforming(gameObject, Shapes).ToArray();
            indices = new int[targets.Length][];
            for (int m = 0; m < targets.Length; m++)
            {
                indices[m] = new int[Shapes.Length];
                for (int s = 0; s < Shapes.Length; s++)
                {
                    int index = targets[m].sharedMesh.GetBlendShapeIndex(Shapes[s]);
                    indices[m][s] = FaceMeshUtil.Deforms(targets[m].sharedMesh, index) ? index : -1;
                }
            }
        }

        private void LateUpdate()
        {
            System.Array.Clear(desired, 0, desired.Length);
            if (speech != null)
            {
                if (speech.LineSerial != lastLine)
                {
                    lastLine = speech.LineSerial;
                    System.Array.Clear(current, 0, current.Length);
                }
                var profile = speech.PerformanceProfile;
                if (speech.IsSpeaking && profile != null && speech.AnalysedClip == profile.referenceClip)
                {
                    foreach (var cue in profile.referenceExpressions)
                    {
                        float elapsed = speech.PerformanceTime - cue.time;
                        if (elapsed < 0f || elapsed > cue.duration) continue;
                        float envelope = Mathf.SmoothStep(0f, 1f, Mathf.Clamp01(elapsed / 0.4f)) *
                            Mathf.SmoothStep(0f, 1f, Mathf.Clamp01((cue.duration - elapsed) / 0.55f));
                        AddMood(cue.mood, cue.strength * envelope);
                    }
                }
                // Sparse emphasis uses the same selected accents as the body, not raw loudness.
                desired[1] += speech.AccentPulse * 0.13f;
                desired[2] += speech.AccentPulse * 0.09f;
            }
            float k = 1f - Mathf.Exp(-Time.deltaTime / Mathf.Max(0.05f, smoothing));
            float blink = gaze != null ? gaze.BlinkWeight : 0f;
            float closure = mouth != null ? mouth.GetSpeechWeight("lipsPressed") : 0f;
            float rounding = mouth != null ? mouth.GetSpeechWeight("mouthPucker") : 0f;
            for (int s = 0; s < Shapes.Length; s++)
            {
                current[s] = Mathf.Lerp(current[s], Mathf.Clamp01(desired[s]) * strength, k);
                float value = current[s];
                if (s == 5 || s == 6) value *= 1f - blink;
                if (s >= 9)
                {
                    value *= (1f - Mathf.Clamp01(closure)) * (1f - Mathf.Clamp01(rounding));
                    if (mouth != null && mouth.enabled) value += mouth.GetSpeechWeight(Shapes[s]);
                }
                for (int m = 0; m < targets.Length; m++)
                    if (targets[m] != null && indices[m][s] >= 0)
                        targets[m].SetBlendShapeWeight(indices[m][s], Mathf.Clamp01(value) * 100f);
            }
        }

        private void AddMood(ConversationMood mood, float weight)
        {
            switch (mood)
            {
                case ConversationMood.Warm:
                    desired[7] += .12f * weight; desired[8] += .12f * weight;
                    desired[9] += .16f * weight; desired[10] += .13f * weight;
                    desired[1] += .06f * weight; desired[2] += .04f * weight;
                    break;
                case ConversationMood.Thinking:
                    desired[1] += .16f * weight; desired[2] += .07f * weight;
                    desired[5] += .035f * weight; desired[6] += .035f * weight;
                    break;
                case ConversationMood.Concern:
                    desired[0] += .16f * weight;
                    desired[3] += .07f * weight; desired[4] += .07f * weight;
                    break;
                case ConversationMood.Emphasis:
                    desired[1] += .18f * weight; desired[2] += .15f * weight;
                    desired[0] += .05f * weight;
                    break;
            }
        }

        private void OnDisable()
        {
            if (targets == null) return;
            for (int m = 0; m < targets.Length; m++)
                for (int s = 0; s < Shapes.Length; s++)
                    if (targets[m] != null && indices[m][s] >= 0)
                        targets[m].SetBlendShapeWeight(indices[m][s],
                            s >= 9 && mouth != null && mouth.enabled ? mouth.GetSpeechWeight(Shapes[s]) * 100f : 0f);
        }
    }
}
