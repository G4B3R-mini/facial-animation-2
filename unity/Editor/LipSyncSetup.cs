// Runtime lipsync for Helen via uLipSync.
//
//   Tools > Tripo Face Rig > 5. Setup Runtime LipSync
//
// Replaces the baked Rhubarb visemes, which cannot work for LLM/TTS generated
// speech because the audio does not exist until runtime. uLipSync analyses
// whatever the AudioSource is playing and drives the vrc.v_* blendshapes the
// rig already carries.
//
// Layout, which matters: uLipSync receives audio through OnAudioFilterRead, so
// it must sit on the SAME GameObject as the AudioSource. uLipSyncBlendShape can
// live anywhere but targets one SkinnedMeshRenderer - the head, since the hair
// and brow objects carry inert copies of the same 72 shapes.
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Events;
using UnityEngine;

namespace TripoFaceRig.EditorTools
{
    public static class HelenLipSyncSetup
    {
        private const string CharacterName = "helen";
        private const string ProfileDir = "Assets/Animations/LipSync";
        private const string ProfileAsset = ProfileDir + "/Helen-LipSync-Profile.asset";

        // Five vowels alone cannot match words: the lips never close on M/B/P and
        // every consonant is approximated by the nearest vowel, so timing lands
        // but the shapes are wrong. N and F are added and calibrated from the
        // Rhubarb cues that correspond to them.
        private static readonly (string phoneme, string shape)[] Map =
        {
            ("A", "vrc.v_aa"),
            ("E", "vrc.v_E"),
            ("I", "vrc.v_I"),
            ("O", "vrc.v_O"),
            ("U", "vrc.v_U"),
            ("N", "vrc.v_PP"),   // lips closed: P B M
        };

        // F/V was tried and dropped: the reference clip has 3 Rhubarb G cues
        // totalling 0.26s, too little to train a phoneme. An UNTRAINED phoneme is
        // not merely useless, it is destructive - see RepairProfile.

        [MenuItem("Tools/Tripo Face Rig/5. Setup Runtime LipSync")]
        public static void Setup()
        {
            var go = GameObject.Find(CharacterName);
            if (go == null)
            {
                Debug.LogError($"[TripoFaceRig] No '{CharacterName}' in the open scene.");
                return;
            }

            // The head is the mesh whose vrc.v_aa actually DEFORMS vertices.
            // Picking by vertex count wires uLipSync to the hair, which carries an
            // inert copy of all 72 shapes and is denser than the head.
            var head = FaceMeshUtil.FindDeformingRenderer(go, "vrc.v_aa");
            if (head == null)
            {
                Debug.LogError("[TripoFaceRig] No mesh has a vrc.v_aa shape that deforms anything.");
                return;
            }
            Debug.Log($"[TripoFaceRig] Mouth renderer: '{head.name}' ({head.sharedMesh.vertexCount} verts).");

            // --- profile: copy a bundled one in so it can be calibrated per voice
            Directory.CreateDirectory(ProfileDir);
            var profile = AssetDatabase.LoadAssetAtPath<uLipSync.Profile>(ProfileAsset);
            if (profile == null)
            {
                var src = AssetDatabase.FindAssets("t:uLipSync.Profile")
                    .Select(AssetDatabase.GUIDToAssetPath)
                    .FirstOrDefault(p => p.Contains("Female")) ??
                    AssetDatabase.FindAssets("t:uLipSync.Profile")
                    .Select(AssetDatabase.GUIDToAssetPath).FirstOrDefault();
                if (src != null && AssetDatabase.CopyAsset(src, ProfileAsset))
                {
                    AssetDatabase.Refresh();
                    profile = AssetDatabase.LoadAssetAtPath<uLipSync.Profile>(ProfileAsset);
                    Debug.Log($"[TripoFaceRig] Copied profile from {src} to {ProfileAsset}.");
                }
            }
            if (profile == null)
            {
                Debug.LogWarning("[TripoFaceRig] No uLipSync Profile found to copy. " +
                                 "Create one via Assets > Create > uLipSync > Profile and assign it.");
            }

            if (profile != null)
            {
                RepairProfile(profile);

                var existing = new System.Collections.Generic.HashSet<string>(profile.GetPhonemeNames());
                foreach (var (phoneme, _) in Map)
                {
                    if (existing.Contains(phoneme)) continue;
                    profile.AddMfcc(phoneme);
                    Debug.LogWarning($"[TripoFaceRig] Added phoneme '{phoneme}'. It is UNTRAINED " +
                                     "until step 6 runs, and an untrained phoneme silences the " +
                                     "whole mouth - run step 6 before pressing Play.");
                }
                EditorUtility.SetDirty(profile);
                AssetDatabase.SaveAssets();
            }

            // --- blendshape driver
            var bs = go.GetComponent<uLipSync.uLipSyncBlendShape>();
            if (bs == null) bs = go.AddComponent<uLipSync.uLipSyncBlendShape>();
            Undo.RecordObject(bs, "Setup uLipSync blendshapes");
            bs.skinnedMeshRenderer = head;
            bs.blendShapes.Clear();

            var mesh = head.sharedMesh;
            int mapped = 0;
            foreach (var (phoneme, shape) in Map)
            {
                int idx = mesh.GetBlendShapeIndex(shape);
                if (idx < 0)
                {
                    Debug.LogWarning($"[TripoFaceRig] '{shape}' not on {head.name}; skipping {phoneme}.");
                    continue;
                }
                bs.blendShapes.Add(new uLipSync.uLipSyncBlendShape.BlendShapeInfo
                {
                    phoneme = phoneme,
                    index = idx,
                    maxWeight = 1f
                });
                mapped++;
            }
            EditorUtility.SetDirty(bs);

            // --- analyser, which must share the GameObject with the AudioSource
            var src2 = go.GetComponent<AudioSource>();
            if (src2 == null) src2 = go.AddComponent<AudioSource>();
            var uls = go.GetComponent<uLipSync.uLipSync>();
            if (uls == null) uls = go.AddComponent<uLipSync.uLipSync>();
            Undo.RecordObject(uls, "Setup uLipSync");
            if (profile != null) uls.profile = profile;
            // Blend by phoneme ratio instead of snapping to the single best match;
            // winner-take-all reads as the mouth flicking between fixed poses.
            bs.usePhonemeBlend = true;

            // wire onLipSyncUpdate -> blendShape.OnLipSyncUpdate, without duplicating
            bool already = false;
            for (int i = 0; i < uls.onLipSyncUpdate.GetPersistentEventCount(); i++)
            {
                if (uls.onLipSyncUpdate.GetPersistentTarget(i) == bs &&
                    uls.onLipSyncUpdate.GetPersistentMethodName(i) == "OnLipSyncUpdate")
                { already = true; break; }
            }
            if (!already)
                UnityEventTools.AddPersistentListener(uls.onLipSyncUpdate, bs.OnLipSyncUpdate);
            EditorUtility.SetDirty(uls);

            UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(go.scene);
            Debug.Log($"[TripoFaceRig] Runtime lipsync ready on '{go.name}': " +
                      $"renderer '{head.name}', {mapped}/{Map.Length} phonemes mapped, " +
                      $"profile {(profile != null ? profile.name : "MISSING")}.");
            var leftover = go.GetComponent<LipSyncAutoCalibrate>();
            var fppChk = go.GetComponent<FacePerformancePlayer>();
            var sgdChk = go.GetComponent<SpeechGestureDriver>();
            bool stuck = (leftover != null && leftover.enabled) ||
                         (fppChk != null && !fppChk.enabled && sgdChk != null && !sgdChk.enabled);
            if (stuck)
                Debug.LogError("[TripoFaceRig] This scene is still in CALIBRATION MODE: the dialogue " +
                               "and gesture drivers are disabled, so there will be no audio and she " +
                               "will stand idle. Run step 7 to restore normal playback.");

            Debug.LogWarning("[TripoFaceRig] The BAKED face clip also animates vrc.v_* shapes and " +
                             "will fight uLipSync. Set the Face layer weight to 0 (or use a " +
                             "controller without that clip) when testing runtime lipsync.");
        }

        /// <summary>
        /// Strips phonemes carrying no real calibration data.
        ///
        /// AddMfcc seeds a new phoneme with 16 ALL-ZERO calibration entries, so an
        /// uncalibrated phoneme has a zero-vector mean. In the standardized MFCC
        /// space that sits at the origin, near-equidistant from every real sound,
        /// so it scores highly on every frame. uLipSyncBlendShape then divides each
        /// weight by the SUM across all mapped shapes, so one origin phoneme drags
        /// every genuine vowel's share toward zero and the mouth stops moving.
        ///
        /// So: a phoneme is either trained or absent. Never left at zero.
        /// </summary>
        private static void RepairProfile(uLipSync.Profile profile)
        {
            for (int i = profile.mfccs.Count - 1; i >= 0; i--)
            {
                var d = profile.mfccs[i];
                bool hasData = false;
                foreach (var c in d.mfccCalibrationDataList)
                {
                    if (c.array == null) continue;
                    foreach (var v in c.array)
                        if (Mathf.Abs(v) > 1e-9f) { hasData = true; break; }
                    if (hasData) break;
                }
                if (hasData) continue;

                Debug.LogWarning($"[TripoFaceRig] Removing untrained phoneme '{d.name}' - " +
                                 "a zero-mean phoneme suppresses every other shape.");
                profile.RemoveMfcc(i);
            }
        }

        [MenuItem("Tools/Tripo Face Rig/5b. Toggle Face Layer (baked visemes)")]
        public static void ToggleFaceLayer()
        {
            var go = GameObject.Find(CharacterName);
            var animator = go != null ? go.GetComponentInChildren<Animator>() : null;
            if (animator == null || animator.layerCount < 2)
            {
                Debug.LogWarning("[TripoFaceRig] No animator with a Face layer found.");
                return;
            }
            float w = animator.GetLayerWeight(1) > 0.5f ? 0f : 1f;
            animator.SetLayerWeight(1, w);
            Debug.Log($"[TripoFaceRig] Face layer weight -> {w}. " +
                      (w == 0f ? "Baked visemes OFF; uLipSync drives the mouth."
                               : "Baked visemes ON; uLipSync will be overridden."));
        }

        private const string CuesAsset = ProfileDir + "/helen_dialogue_cues.json";
        private const string DialogueAsset = "Assets/Audio/Dialogue/helen_dialogue.wav";

        [MenuItem("Tools/Tripo Face Rig/6. Auto-Calibrate LipSync (then press Play)")]
        public static void SetupCalibration()
        {
            var go = GameObject.Find(CharacterName);
            if (go == null) { Debug.LogError($"[TripoFaceRig] No '{CharacterName}' in the scene."); return; }

            var uls = go.GetComponent<uLipSync.uLipSync>();
            if (uls == null) { Debug.LogError("[TripoFaceRig] Run step 5 first."); return; }

            var cues = AssetDatabase.LoadAssetAtPath<TextAsset>(CuesAsset);
            var clip = AssetDatabase.LoadAssetAtPath<AudioClip>(DialogueAsset);
            if (cues == null || clip == null)
            {
                Debug.LogError($"[TripoFaceRig] Need {CuesAsset} and {DialogueAsset}.");
                return;
            }

            var cal = go.GetComponent<LipSyncAutoCalibrate>();
            if (cal == null) cal = go.AddComponent<LipSyncAutoCalibrate>();
            var so = new SerializedObject(cal);
            so.FindProperty("lipSync").objectReferenceValue = uls;
            so.FindProperty("audioSource").objectReferenceValue = go.GetComponent<AudioSource>();
            so.FindProperty("clip").objectReferenceValue = clip;
            so.FindProperty("rhubarbCues").objectReferenceValue = cues;
            so.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(cal);

            // The baked face clip animates the same shapes and would fight the
            // analyser; calibration must hear the voice, not watch the clip.
            var animator = go.GetComponentInChildren<Animator>();
            if (animator != null && animator.layerCount > 1) animator.SetLayerWeight(1, 0f);

            // Other players would restart the audio mid-calibration.
            var fpp = go.GetComponent<FacePerformancePlayer>();
            if (fpp != null) fpp.enabled = false;
            var sgd = go.GetComponent<SpeechGestureDriver>();
            if (sgd != null) sgd.enabled = false;

            UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(go.scene);

            // This step deliberately leaves the scene BROKEN for normal playback:
            // the two components that start the dialogue audio and drive the body
            // are disabled so they cannot restart the clip mid-calibration. Only
            // step 7 puts them back. Play-mode cannot do it, because component
            // state set during Play reverts on exit - so it has to be an explicit
            // editor action, and therefore has to be impossible to miss.
            Debug.LogWarning(
                "[TripoFaceRig] CALIBRATION MODE ARMED - the scene will NOT play dialogue " +
                "until you run step 7.\n" +
                "  1. Press Play, let the clip run to the very end, then exit Play.\n" +
                "  2. Run 'Tools > Tripo Face Rig > 7. Finish Runtime Face Setup'.\n" +
                "FacePerformancePlayer and SpeechGestureDriver are now DISABLED, so until " +
                "step 7 runs she will be silent and stand idle. That is expected, not a fault.");
        }

        [MenuItem("Tools/Tripo Face Rig/7. Finish Runtime Face Setup")]
        public static void FinishRuntime()
        {
            var go = GameObject.Find(CharacterName);
            if (go == null) { Debug.LogError($"[TripoFaceRig] No '{CharacterName}' in the scene."); return; }

            // The ambient face clip must loop; it is 10s of blinks and gaze meant
            // to run under any dialogue length.
            var mi = AssetImporter.GetAtPath("Assets/Town/helen.fbx") as ModelImporter;
            if (mi != null)
            {
                var clips = mi.defaultClipAnimations;
                for (int i = 0; i < clips.Length; i++) clips[i].loopTime = true;
                mi.clipAnimations = clips;
                EditorUtility.SetDirty(mi);
                mi.SaveAndReimport();
                Debug.Log($"[TripoFaceRig] Set {clips.Length} face clip(s) to loop.");
            }

            // Face layer back to full weight: it no longer contains visemes, so it
            // cannot fight uLipSync, and at weight 0 the blinks would be lost too.
            var animator = go.GetComponentInChildren<Animator>();
            if (animator != null && animator.layerCount > 1) animator.SetLayerWeight(1, 1f);

            var brow = go.GetComponent<SpeechBrowDriver>();
            if (brow == null) brow = go.AddComponent<SpeechBrowDriver>();
            var so = new SerializedObject(brow);
            so.FindProperty("speech").objectReferenceValue = go.GetComponent<SpeechGestureDriver>();
            so.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(brow);

            var cal = go.GetComponent<LipSyncAutoCalibrate>();
            if (cal != null) cal.enabled = false;
            var fpp = go.GetComponent<FacePerformancePlayer>();
            if (fpp != null) fpp.enabled = false;   // baked-take player; not used at runtime
            var sgd = go.GetComponent<SpeechGestureDriver>();
            if (sgd != null)
            {
                sgd.enabled = true;
                // Nothing else starts audio now that FacePerformancePlayer is off,
                // and with no audio uLipSync has nothing to analyse - the mouth
                // just sits still. Point the driver at the sample clip so Play
                // works standalone; the TTS system calls Speak() instead.
                var clip = AssetDatabase.LoadAssetAtPath<AudioClip>(DialogueAsset);
                var sso = new SerializedObject(sgd);
                sso.FindProperty("testClip").objectReferenceValue = clip;
                sso.FindProperty("speakOnStart").boolValue = true;
                sso.ApplyModifiedPropertiesWithoutUndo();
                EditorUtility.SetDirty(sgd);
            }

            UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(go.scene);
            Debug.Log("[TripoFaceRig] Runtime face ready: ambient clip looping on the Face layer, " +
                      "uLipSync on the mouth, SpeechBrowDriver on browInnerUp, gestures on the body. " +
                      "Drive everything with SpeechGestureDriver.Speak(clip).");
        }
    }
}
