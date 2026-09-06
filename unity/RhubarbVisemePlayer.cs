using System;
using System.Collections.Generic;
using UnityEngine;

namespace TripoFaceRig
{
    /// <summary>
    /// Drives the face from Rhubarb cues, on independent articulator channels,
    /// with coarticulation.
    ///
    /// Two things separate this from the first version.
    ///
    /// ONE: it drives ARKit shapes directly instead of the eight lumped vrc.v_*
    /// visemes. Each vrc shape bakes a FIXED ratio of jaw to lip pose - v_aa is
    /// mouthWide 0.42 plus jawOpen 0.82, permanently welded together - so the jaw
    /// could never be varied independently, and blending two visemes counted
    /// jawOpen twice. Splitting them into channels fixes the double-count and is
    /// what lets coarticulation work per-articulator, which is the point below.
    ///
    /// TWO: it blends by dominance rather than smoothing toward the current cue.
    /// Real articulators anticipate and carry over - the lips round for the "oo"
    /// in "school" during the "s", because the tongue and the lips are steered by
    /// different muscles on different timescales. A single smoothing constant
    /// cannot express that. Here each channel has its own reach (the jaw is slow
    /// and wide, lips are quicker, the tongue quicker still) and each cue has a
    /// dominance saying how hard it insists on its target. A lip closure for
    /// P/B/M insists almost absolutely, because a bilabial that fails to close
    /// reads instantly as wrong; a schwa barely insists at all.
    ///
    /// This is the Cohen-Massaro dominance model, simplified: a Gaussian per cue
    /// per channel, normalised across the cues in reach.
    /// </summary>
    public sealed class RhubarbVisemePlayer : MonoBehaviour
    {
        public enum Articulation
        {
            /// <summary>Independent ARKit channels with coarticulation.</summary>
            ArkitCoarticulated,
            /// <summary>The original eight lumped vrc.v_* visemes, for A/B.</summary>
            LumpedVisemes,
        }

        [SerializeField] private AudioSource audioSource;
        [SerializeField] private Articulation mode = Articulation.ArkitCoarticulated;

        [Tooltip("Rhubarb output (-f json). Leave empty when cues arrive at runtime via Play().")]
        [SerializeField] private TextAsset cuesJson;

        [Tooltip("Meshes to drive. Auto-filled with every mesh whose shapes actually deform.")]
        [SerializeField] private SkinnedMeshRenderer[] targets;

        [Tooltip("Scales every channel's reach. Above ~1.4 slurs words together; " +
                 "below ~0.6 loses the anticipation that makes it read as speech.")]
        [Range(0.4f, 2f)] [SerializeField] private float coarticulation = 1f;

        [Tooltip("Overall strength.")]
        [Range(0f, 1.5f)] [SerializeField] private float scale = 1f;

        [Tooltip("How much syllable loudness varies articulation. 0 drives every cue at full " +
                 "strength, which over-enunciates and reads synthetic; 1 follows the envelope fully.")]
        [Range(0f, 1f)] [SerializeField] private float dynamics = 1f;

        [Tooltip("Only used by LumpedVisemes mode.")]
        [Range(0.01f, 0.15f)] [SerializeField] private float blendTime = 0.045f;

        [SerializeField] private bool diagnose = true;

        // ------------------------------------------------------------ channels
        //
        // Reach (sigma, seconds) is per articulator, not per phoneme, because it
        // is a fact about the muscle rather than the sound. The jaw is a heavy
        // hinge and blends over a long window; the lips are faster; the tongue
        // is the fastest thing in the mouth and must not smear or every stop
        // consonant turns to mush.
        private struct Channel
        {
            public string shape;
            public float sigma;
            /// <summary>
            /// How much this articulator reduces when the syllable is quiet, 0..1.
            ///
            /// Speech is not uniformly articulated: unstressed syllables are
            /// reduced almost to nothing while stressed ones over-articulate, and
            /// driving every cue at full strength is a large part of what reads as
            /// synthetic. But reduction is not uniform ACROSS articulators either.
            /// The jaw tracks loudness closely - a quiet vowel barely opens. A
            /// closure does not: a whispered "m" still shuts the lips completely,
            /// because a bilabial that fails to close is not a quiet bilabial, it
            /// is a different sound. So closures get a low sensitivity and stay
            /// near full regardless of level.
            /// </summary>
            public float sens;
            public Channel(string shape, float sigma, float sens)
            { this.shape = shape; this.sigma = sigma; this.sens = sens; }
        }

        private static readonly Channel[] Channels =
        {                                //          sigma   loudness sensitivity
            new Channel("jawOpen",            0.090f, 0.75f),
            new Channel("mouthWide",          0.055f, 0.45f),
            new Channel("mouthFunnel",        0.060f, 0.45f),
            new Channel("mouthPucker",        0.060f, 0.40f),
            new Channel("lipsPressed",        0.038f, 0.12f),  // closures must be crisp
            new Channel("mouthFF",            0.040f, 0.15f),
            new Channel("mouthClose",         0.040f, 0.12f),
            new Channel("mouthPressLeft",     0.038f, 0.15f),
            new Channel("mouthPressRight",    0.038f, 0.15f),
            new Channel("mouthStretchLeft",   0.055f, 0.45f),
            new Channel("mouthStretchRight",  0.055f, 0.45f),
            new Channel("mouthUpperUpLeft",   0.060f, 0.55f),
            new Channel("mouthUpperUpRight",  0.060f, 0.55f),
            new Channel("mouthLowerDownLeft", 0.060f, 0.55f),
            new Channel("mouthLowerDownRight",0.060f, 0.55f),
            new Channel("mouthRollLower",     0.045f, 0.20f),
            new Channel("mouthRollUpper",     0.045f, 0.20f),
            new Channel("mouthSmileLeft",     0.070f, 0.40f),
            new Channel("mouthSmileRight",    0.070f, 0.40f),
            new Channel("tongueOut",          0.035f, 0.30f),
            new Channel("tongueUp",           0.035f, 0.15f),
        };

        private static int Ch(string name)
        {
            for (int i = 0; i < Channels.Length; i++) if (Channels[i].shape == name) return i;
            return -1;
        }

        // ------------------------------------------------------------- poses
        //
        // jawOpen comes from the baked pipeline's tuned jaw angles divided by the
        // 22 degree reference open, so these are the same numbers that already
        // looked right, not fresh guesses: A 0, B 4, C 10, D 18, E 8, F 3, G 2,
        // H 9 degrees. The mouth keys likewise come straight from that table. The
        // extra ARKit channels are what the lumped visemes could not express.
        private sealed class Pose
        {
            public readonly float[] w = new float[Channels.Length];
            public float dominance = 1f;
            public Pose Set(string shape, float v) { int i = Ch(shape); if (i >= 0) w[i] = v; return this; }
            public Pose Pair(string l, string r, float v) { Set(l, v); Set(r, v); return this; }
            public Pose Dom(float d) { dominance = d; return this; }
        }

        private static readonly Dictionary<string, Pose> Poses = new Dictionary<string, Pose>
        {
            // Rest. Low dominance so a neighbouring sound carries through a short
            // gap instead of the mouth snapping shut between every word.
            { "X", new Pose().Dom(0.45f) },

            // P B M. Lips genuinely shut. Highest dominance in the table: a
            // bilabial that fails to close is the single most obvious lipsync
            // failure, so it must win against whatever vowel surrounds it.
            { "A", new Pose()
                .Set("lipsPressed", 1.00f)
                .Set("mouthClose", 0.35f)
                .Pair("mouthPressLeft", "mouthPressRight", 0.45f)
                .Set("jawOpen", 0f)
                .Dom(2.6f) },

            // Teeth close: T D N S K, and EE. Wide and barely open.
            { "B", new Pose()
                .Set("jawOpen", 0.18f)
                .Set("mouthWide", 0.85f)
                .Pair("mouthStretchLeft", "mouthStretchRight", 0.30f)
                .Pair("mouthSmileLeft", "mouthSmileRight", 0.10f)
                .Dom(1.0f) },

            // EH / AE.
            { "C", new Pose()
                .Set("jawOpen", 0.45f)
                .Set("mouthWide", 0.50f)
                .Pair("mouthStretchLeft", "mouthStretchRight", 0.20f)
                .Dom(0.9f) },

            // AA, the widest open. Lips part vertically rather than stretching.
            { "D", new Pose()
                .Set("jawOpen", 0.82f)
                .Set("mouthWide", 0.25f)
                .Pair("mouthUpperUpLeft", "mouthUpperUpRight", 0.22f)
                .Pair("mouthLowerDownLeft", "mouthLowerDownRight", 0.28f)
                .Dom(1.1f) },

            // AO / ER, rounded and open.
            { "E", new Pose()
                .Set("jawOpen", 0.36f)
                .Set("mouthFunnel", 0.90f)
                .Set("mouthPucker", 0.20f)
                .Dom(1.0f) },

            // UW / OW / W, pursed and nearly closed. Rounding reaches a long way
            // backwards in real speech, which the dominance model now expresses.
            { "F", new Pose()
                .Set("jawOpen", 0.14f)
                .Set("mouthPucker", 0.95f)
                .Set("mouthFunnel", 0.30f)
                .Dom(1.4f) },

            // F V. Lower lip tucks under the top teeth - mouthRollLower is the
            // shape that actually says "labiodental"; mouthFF alone reads flat.
            { "G", new Pose()
                .Set("jawOpen", 0.09f)
                .Set("mouthFF", 1.00f)
                .Set("mouthRollLower", 0.45f)
                .Pair("mouthUpperUpLeft", "mouthUpperUpRight", 0.18f)
                .Dom(1.9f) },

            // L. The tongue is the whole point of this shape.
            { "H", new Pose()
                .Set("jawOpen", 0.41f)
                .Set("mouthWide", 0.30f)
                .Set("tongueOut", 0.04f)
                .Set("tongueUp", 0.70f)
                .Dom(1.2f) },
        };

        // Lumped fallback, unchanged, for A/B against the above.
        private static readonly Dictionary<string, string> Lumped = new Dictionary<string, string>
        {
            { "A", "vrc.v_PP" }, { "B", "vrc.v_I" }, { "C", "vrc.v_E" }, { "D", "vrc.v_aa" },
            { "E", "vrc.v_O" },  { "F", "vrc.v_U" }, { "G", "vrc.v_FF" }, { "H", "vrc.v_nn" },
        };
        private static readonly string[] LumpedShapes =
        {
            "vrc.v_PP", "vrc.v_I", "vrc.v_E", "vrc.v_aa",
            "vrc.v_O", "vrc.v_U", "vrc.v_FF", "vrc.v_nn",
        };

        [Serializable] private class Cue { public float start; public float end; public string value; }
        [Serializable] private class CueFile { public List<Cue> mouthCues; }

        private List<Cue> cues;
        private SpeechAnalysis.Result analysis;
        private AudioClip analysedClip;
        private float[] current;
        private float[] target;
        private int[][] indices;      // [renderer][channel or lumped shape]
        private string[] activeShapes;

        public bool HasCues => cues != null && cues.Count > 0;

        private void Awake()
        {
            if (audioSource == null) audioSource = GetComponent<AudioSource>();
            Rebuild();
            if (cuesJson != null) LoadCues(cuesJson.text);
        }

        private void Rebuild()
        {
            activeShapes = new string[mode == Articulation.LumpedVisemes
                ? LumpedShapes.Length : Channels.Length];
            for (int i = 0; i < activeShapes.Length; i++)
                activeShapes[i] = mode == Articulation.LumpedVisemes
                    ? LumpedShapes[i] : Channels[i].shape;

            current = new float[activeShapes.Length];
            target = new float[activeShapes.Length];

            if (targets == null || targets.Length == 0)
            {
                // Deformation test, never vertex count. Separating hair by loose
                // parts copied every shape key onto the hair, which therefore
                // carries the full set at a HIGHER vertex count than the head
                // while deforming nothing. That has picked the wrong mesh twice,
                // once in Blender and once in C#.
                targets = FaceMeshUtil.FindAllDeforming(gameObject, activeShapes).ToArray();
            }

            indices = new int[targets.Length][];
            var missing = new List<string>();
            for (int t = 0; t < targets.Length; t++)
            {
                indices[t] = new int[activeShapes.Length];
                var mesh = targets[t] != null ? targets[t].sharedMesh : null;
                for (int c = 0; c < activeShapes.Length; c++)
                {
                    indices[t][c] = mesh != null ? mesh.GetBlendShapeIndex(activeShapes[c]) : -1;
                    if (!FaceMeshUtil.Deforms(mesh, indices[t][c])) indices[t][c] = -1;
                }
            }

            for (int c = 0; c < activeShapes.Length; c++)
            {
                bool present = false;
                for (int t = 0; t < targets.Length; t++) present |= indices[t][c] >= 0;
                if (!present) missing.Add(activeShapes[c]);
            }

            if (targets.Length == 0)
                Debug.LogWarning("[TripoFaceRig] No mesh deforms; the mouth will not move.", this);
            else if (missing.Count > 0 && diagnose)
                // Not fatal: a rig without mouthRollLower simply loses that nuance.
                Debug.Log($"[TripoFaceRig] {activeShapes.Length - missing.Count}/{activeShapes.Length} " +
                          $"channels present. Absent: {string.Join(", ", missing)}", this);
        }

        public bool LoadCues(string json)
        {
            var parsed = JsonUtility.FromJson<CueFile>(json);
            if (parsed == null || parsed.mouthCues == null || parsed.mouthCues.Count == 0)
            {
                Debug.LogError("[TripoFaceRig] Could not parse mouthCues from the Rhubarb JSON.", this);
                cues = null;
                return false;
            }
            cues = parsed.mouthCues;
            if (diagnose)
                Debug.Log($"[TripoFaceRig] {cues.Count} cues over {cues[cues.Count - 1].end:0.00}s " +
                          $"({mode}).", this);
            return true;
        }

        public void Play(AudioClip clip, string cuesJsonText)
        {
            if (!LoadCues(cuesJsonText)) return;
            if (audioSource == null) return;
            audioSource.clip = clip;
            audioSource.Stop();
            audioSource.time = 0f;
            audioSource.Play();
        }

        private void LateUpdate()
        {
            if (targets == null || targets.Length == 0 || current == null) return;

            bool speaking = audioSource != null && audioSource.isPlaying && HasCues;
            float t = speaking ? audioSource.time : 0f;

            // Loudness of the syllable being spoken right now, 0..1. Falls back to
            // 1 (fully articulated) when the clip could not be analysed, so a
            // failure here quietens nothing.
            float level = 1f;
            if (speaking)
            {
                EnsureAnalysis();
                if (analysis != null) level = Mathf.Clamp01(analysis.LevelAt(t));
            }

            if (!speaking)
                Array.Clear(target, 0, target.Length);
            else if (mode == Articulation.LumpedVisemes)
                LumpedTargets(t);
            else
                CoarticulatedTargets(t, level);

            if (mode == Articulation.LumpedVisemes)
            {
                float k = 1f - Mathf.Exp(-Time.deltaTime / Mathf.Max(0.001f, blendTime));
                for (int c = 0; c < current.Length; c++) current[c] = Mathf.Lerp(current[c], target[c], k);
            }
            else
            {
                // The dominance blend already produces a continuous curve, so a
                // second smoothing pass would only add lag. One light step keeps
                // a frame-rate hitch from showing as a jump.
                float k = 1f - Mathf.Exp(-Time.deltaTime / 0.012f);
                for (int c = 0; c < current.Length; c++) current[c] = Mathf.Lerp(current[c], target[c], k);
            }

            for (int r = 0; r < targets.Length; r++)
            {
                if (targets[r] == null) continue;
                for (int c = 0; c < current.Length; c++)
                {
                    int idx = indices[r][c];
                    if (idx >= 0) targets[r].SetBlendShapeWeight(idx, current[c] * 100f);
                }
            }
        }

        /// <summary>
        /// Weighted blend of every cue within reach, per channel.
        ///
        /// weight(cue, channel) = dominance * exp(-((t - centre) / sigma)^2)
        ///
        /// Normalising by the summed weight is what makes this a blend rather
        /// than an accumulation: three overlapping cues cannot drive jawOpen past
        /// its own maximum, which is exactly the double-counting that made the
        /// lumped visemes impossible to overlap safely.
        /// </summary>
        private void CoarticulatedTargets(float t, float level)
        {
            Array.Clear(target, 0, target.Length);

            for (int c = 0; c < Channels.Length; c++)
            {
                // (1 - sens) is the floor this articulator keeps even in silence,
                // so closures stay closed while the jaw is free to go slack.
                float sens = Channels[c].sens * dynamics;
                float gain = (1f - sens) + sens * level;

                float sigma = Channels[c].sigma * coarticulation;
                float reach = sigma * 2.5f;          // beyond this the Gaussian is negligible
                float sum = 0f, acc = 0f;

                for (int i = 0; i < cues.Count; i++)
                {
                    var cue = cues[i];
                    float centre = 0.5f * (cue.start + cue.end);
                    float dt = t - centre;
                    // A long cue should not be treated as an instant: clamp the
                    // distance to its own span so a held vowel stays fully present
                    // throughout instead of fading from its midpoint.
                    float half = 0.5f * Mathf.Max(0f, cue.end - cue.start);
                    float d = Mathf.Max(0f, Mathf.Abs(dt) - half);
                    if (d > reach) continue;

                    if (!Poses.TryGetValue(cue.value, out var pose)) continue;
                    float g = pose.dominance * Mathf.Exp(-(d * d) / (sigma * sigma));
                    acc += g * pose.w[c];
                    sum += g;
                }

                target[c] = sum > 1e-6f ? Mathf.Clamp01(acc / sum) * scale * gain : 0f;
            }
        }

        private void LumpedTargets(float t)
        {
            Array.Clear(target, 0, target.Length);
            var cue = CueAt(t);
            if (cue == null || !Lumped.TryGetValue(cue.value, out var shape)) return;
            int i = Array.IndexOf(LumpedShapes, shape);
            if (i >= 0) target[i] = scale;
        }

        private int cursor;
        private Cue CueAt(float t)
        {
            if (cues == null || cues.Count == 0) return null;
            if (cursor >= cues.Count || cues[cursor].start > t) cursor = 0;
            while (cursor + 1 < cues.Count && cues[cursor + 1].start <= t) cursor++;
            var c = cues[cursor];
            return (t >= c.start && t <= c.end) ? c : null;
        }

        /// <summary>
        /// Analyse whatever clip is loaded, once. Re-runs only when the clip
        /// changes, which matters for TTS: every line is a new clip.
        /// </summary>
        private void EnsureAnalysis()
        {
            var clip = audioSource != null ? audioSource.clip : null;
            if (clip == null) { analysis = null; analysedClip = null; return; }
            if (ReferenceEquals(clip, analysedClip)) return;
            analysedClip = clip;
            var speech = GetComponent<SpeechGestureDriver>();
            analysis = speech != null && speech.AnalysedClip == clip && speech.Analysis != null
                ? speech.Analysis : SpeechAnalysis.Analyse(clip);
        }

        /// <summary>Unmixed speech coefficient, used by the final expression mixer without accumulating last frame.</summary>
        public float GetSpeechWeight(string shape)
        {
            if (activeShapes == null || current == null) return 0f;
            int index = Array.IndexOf(activeShapes, shape);
            return index >= 0 ? current[index] : 0f;
        }

        /// <summary>Drop everything to rest. Call when a line is cut short.</summary>
        public void ClearMouth()
        {
            if (targets == null || current == null || indices == null) return;
            Array.Clear(current, 0, current.Length);
            for (int r = 0; r < targets.Length; r++)
            {
                if (targets[r] == null) continue;
                for (int c = 0; c < current.Length; c++)
                    if (indices[r][c] >= 0) targets[r].SetBlendShapeWeight(indices[r][c], 0f);
            }
        }

        /// <summary>Switch modes at runtime, clearing the shapes the old mode owned.</summary>
        public void SetMode(Articulation next)
        {
            if (next == mode) return;
            ClearMouth();
            mode = next;
            targets = null;      // re-probe: the two modes test different shapes
            Rebuild();
        }
    }
}
