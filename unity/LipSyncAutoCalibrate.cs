using System;
using System.Collections.Generic;
using UnityEngine;

namespace TripoFaceRig
{
    /// <summary>
    /// Calibrates a uLipSync Profile against a real voice clip automatically.
    ///
    /// Manual calibration means playing a clip and tapping a button while each
    /// vowel happens to sound. We already know exactly when every vowel occurs:
    /// the Rhubarb cue JSON generated for this clip. So play the clip and call
    /// RequestCalibration at the right moments instead.
    ///
    /// Rhubarb uses Preston Blair shapes; the vowel-bearing ones map onto
    /// uLipSync's five as below. Consonant shapes (A closed, G f/v, H l) and rest
    /// (X) are skipped - calibrating a vowel on a closed mouth poisons the profile.
    /// </summary>
    public sealed class LipSyncAutoCalibrate : MonoBehaviour
    {
        [SerializeField] private uLipSync.uLipSync lipSync;
        [SerializeField] private AudioSource audioSource;
        [SerializeField] private AudioClip clip;
        [SerializeField] private TextAsset rhubarbCues;

        [Tooltip("Skip this much at each end of a cue so the sample sits in the steady middle.")]
        [SerializeField] private float cueEdgeGuard = 0.03f;
        [Tooltip("Minimum seconds between samples OF THE SAME phoneme.")]
        [SerializeField] private float sampleInterval = 0.05f;
        [Tooltip("Wipe the profile's existing calibration first. Off = add to it.")]
        [SerializeField] private bool clearExisting = true;

        // Rhubarb shape -> uLipSync phoneme
        private static readonly Dictionary<string, string> ShapeToPhoneme = new Dictionary<string, string>
        {
            { "D", "A" },  // AA, wide open
            { "C", "E" },  // EH / AE
            { "B", "I" },  // EE, teeth close
            { "E", "O" },  // AO / ER, rounded
            { "F", "U" },  // UW / OW, pursed
            { "A", "N" },  // P B M - lips CLOSED. Without this the mouth never shuts.
            // G (F/V) is deliberately absent: only 3 cues totalling 0.26s here,
            // too little to train, and a half-trained phoneme is worse than none.
        };

        [Serializable] private class Cue { public float start; public float end; public string value; }
        [Serializable] private class CueFile { public List<Cue> mouthCues; }

        private List<Cue> cues;
        private readonly Dictionary<string, int> phonemeIndex = new Dictionary<string, int>();
        private readonly Dictionary<string, int> sampleCount = new Dictionary<string, int>();
        // Per phoneme, not global. The closed-lip cues average 96ms against
        // 194-243ms for the vowels, so one global gate let a long vowel sample
        // block the short closure right after it, and N trained on nothing.
        private readonly Dictionary<string, float> lastSample = new Dictionary<string, float>();
        private bool running;

        private void Start()
        {
            if (lipSync == null) lipSync = GetComponent<uLipSync.uLipSync>();
            if (audioSource == null) audioSource = GetComponent<AudioSource>();
            if (lipSync == null || lipSync.profile == null || audioSource == null || rhubarbCues == null)
            {
                Debug.LogError("[TripoFaceRig] AutoCalibrate needs uLipSync (with a Profile), " +
                               "an AudioSource and the Rhubarb cue JSON.", this);
                enabled = false;
                return;
            }

            var parsed = JsonUtility.FromJson<CueFile>(rhubarbCues.text);
            cues = parsed?.mouthCues;
            if (cues == null || cues.Count == 0)
            {
                Debug.LogError("[TripoFaceRig] Could not parse mouthCues from the JSON.", this);
                enabled = false;
                return;
            }

            var names = lipSync.profile.GetPhonemeNames();
            for (int i = 0; i < names.Length; i++) phonemeIndex[names[i]] = i;

            foreach (var p in ShapeToPhoneme.Values)
            {
                if (!phonemeIndex.ContainsKey(p))
                    Debug.LogWarning($"[TripoFaceRig] Profile has no phoneme '{p}'.", this);
                sampleCount[p] = 0;
            }

            if (clearExisting)
            {
                foreach (var p in ShapeToPhoneme.Values)
                {
                    if (!phonemeIndex.TryGetValue(p, out int idx)) continue;
                    lipSync.profile.mfccs[idx].mfccCalibrationDataList.Clear();
                }
                Debug.Log("[TripoFaceRig] Cleared existing calibration for the five vowels.", this);
            }

            if (clip != null) audioSource.clip = clip;
            audioSource.Stop();
            audioSource.time = 0f;
            audioSource.Play();
            running = true;
            Debug.Log($"[TripoFaceRig] Calibrating from {cues.Count} cues over " +
                      $"{audioSource.clip.length:0.0}s. Let it play to the end.", this);
        }

        private void Update()
        {
            if (!running) return;

            if (!audioSource.isPlaying)
            {
                running = false;
                Finish();
                return;
            }

            float t = audioSource.time;

            for (int i = 0; i < cues.Count; i++)
            {
                var c = cues[i];
                // Proportional guard: a flat 30ms each end leaves a 96ms closure
                // with a 36ms window, which at 60fps is often missed entirely.
                float guard = Mathf.Min(cueEdgeGuard, 0.25f * (c.end - c.start));
                if (t < c.start + guard || t > c.end - guard) continue;
                if (!ShapeToPhoneme.TryGetValue(c.value, out var phoneme)) return; // consonant/rest
                if (!phonemeIndex.TryGetValue(phoneme, out int idx)) return;

                float last;
                if (lastSample.TryGetValue(phoneme, out last) && t - last < sampleInterval) return;

                lipSync.RequestCalibration(idx);
                sampleCount[phoneme]++;
                lastSample[phoneme] = t;
                return;
            }
        }

        private void Finish()
        {
            var report = string.Join(", ", new List<string>(sampleCount.Keys)
                .ConvertAll(k => $"{k}={sampleCount[k]}"));
            Debug.Log($"[TripoFaceRig] Calibration samples: {report}", this);

            // A phoneme that trained on nothing keeps a zero-vector mean, which sits
            // at the origin of the standardized space and so scores highly every
            // frame. uLipSyncBlendShape normalises each weight by the sum over all
            // mapped shapes, so one such phoneme drives every real vowel toward zero
            // and the mouth stops moving. Remove it rather than ship it.
            var names = new List<string>(lipSync.profile.GetPhonemeNames());
            foreach (var kv in sampleCount)
            {
                if (kv.Value == 0)
                {
                    int idx = names.IndexOf(kv.Key);
                    if (idx >= 0)
                    {
                        lipSync.profile.RemoveMfcc(idx);
                        Debug.LogError($"[TripoFaceRig] '{kv.Key}' got NO samples and has been " +
                                       "removed - it would have silenced the whole mouth. The clip " +
                                       "has too little of that sound.", this);
                    }
                }
                else if (kv.Value < 5)
                {
                    Debug.LogWarning($"[TripoFaceRig] Only {kv.Value} samples for '{kv.Key}' - " +
                                     "still weak. Use a clip that says it more.", this);
                }
            }

            lipSync.profile.UpdateMeansAndStandardization();
#if UNITY_EDITOR
            UnityEditor.EditorUtility.SetDirty(lipSync.profile);
            UnityEditor.AssetDatabase.SaveAssets();
            Debug.Log("[TripoFaceRig] Profile saved. Exit Play mode; the calibration persists.", this);
#endif
        }
    }
}
