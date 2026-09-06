// Switches Helen's mouth between the two lipsync approaches.
//
//   Tools > Tripo Face Rig > 10. Use Rhubarb Cues (accurate)
//   Tools > Tripo Face Rig > 10b. Use uLipSync (live audio)
//
// They drive the same vrc.v_* blendshapes, so exactly one may be enabled at a
// time or they fight and the loser's shapes are left stranded mid-pose.
//
// Rhubarb is the accurate path and is what production should use: the TTS server
// hands us a finished FILE plus the text the LLM wrote, so real recognition is
// available before playback starts. uLipSync stays for audio we did not generate
// and cannot analyse ahead of time.
using System.IO;
using System.Linq;
using System;
using UnityEditor;
using UnityEngine;

namespace TripoFaceRig.EditorTools
{
    public static class HelenRhubarbSetup
    {
        private const string CharacterName = "helen";
        private const string CuesAsset = "Assets/Animations/LipSync/helen_dialogue_cues.json";
        private const string DialogueAsset = "Assets/Audio/Dialogue/helen_dialogue.wav";

        [MenuItem("Tools/Tripo Face Rig/10. Use Rhubarb Cues (accurate)")]
        public static void UseRhubarb()
        {
            var go = GameObject.Find(CharacterName);
            if (go == null) { Debug.LogError($"[TripoFaceRig] No '{CharacterName}' in the scene."); return; }

            var cues = AssetDatabase.LoadAssetAtPath<TextAsset>(CuesAsset);
            if (cues == null)
            {
                Debug.LogError($"[TripoFaceRig] Missing {CuesAsset}. Generate it with:\n" +
                               "  rhubarb.exe -r pocketSphinx -f json -o <out.json> <clip.wav>\n" +
                               "and add -d <dialog.txt> when you have the line's text, which " +
                               "Rhubarb uses to constrain recognition.");
                return;
            }

            var src = go.GetComponent<AudioSource>();
            if (src == null) src = go.AddComponent<AudioSource>();
            if (src.clip == null)
            {
                var clip = AssetDatabase.LoadAssetAtPath<AudioClip>(DialogueAsset);
                if (clip != null) src.clip = clip;
            }

            var player = go.GetComponent<RhubarbVisemePlayer>();
            if (player == null) player = go.AddComponent<RhubarbVisemePlayer>();
            player.enabled = true;

            var so = new SerializedObject(player);
            so.FindProperty("audioSource").objectReferenceValue = src;
            so.FindProperty("cuesJson").objectReferenceValue = cues;
            // Leave targets empty so Awake resolves them by DEFORMATION rather
            // than by whatever happened to be wired last.
            so.FindProperty("targets").arraySize = 0;
            so.FindProperty("mode").enumValueIndex = 0;   // ArkitCoarticulated
            so.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(player);

            int off = SetLipSyncEnabled(go, false);

            UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(go.scene);
            Debug.Log($"[TripoFaceRig] Rhubarb viseme player active on '{go.name}' " +
                      $"({cues.name}); disabled {off} uLipSync component(s). Press Play.");
            WarnIfFaceLayerFights(go);
        }

        [MenuItem("Tools/Tripo Face Rig/10b. Use uLipSync (live audio)")]
        public static void UseULipSync()
        {
            var go = GameObject.Find(CharacterName);
            if (go == null) { Debug.LogError($"[TripoFaceRig] No '{CharacterName}' in the scene."); return; }

            var player = go.GetComponent<RhubarbVisemePlayer>();
            if (player != null)
            {
                player.ClearMouth();       // do not strand a half-open mouth
                player.enabled = false;
            }
            int on = SetLipSyncEnabled(go, true);

            UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(go.scene);
            Debug.Log($"[TripoFaceRig] uLipSync active again ({on} component(s)); " +
                      "Rhubarb player disabled.");
        }

        private static int SetLipSyncEnabled(GameObject go, bool on)
        {
            int n = 0;
            foreach (var c in go.GetComponentsInChildren<MonoBehaviour>(true))
            {
                if (c == null) continue;
                var name = c.GetType().Name;
                if (name != "uLipSync" && name != "uLipSyncBlendShape") continue;
                c.enabled = on;
                EditorUtility.SetDirty(c);
                n++;
            }
            return n;
        }

        private static void WarnIfFaceLayerFights(GameObject go)
        {
            var an = go.GetComponentInChildren<Animator>();
            if (an == null || an.runtimeAnimatorController == null) return;
            var clips = an.runtimeAnimatorController.animationClips;
            bool bakedVisemes = clips.Any(c => c != null &&
                UnityEditor.AnimationUtility.GetCurveBindings(c)
                    .Any(b => b.propertyName.Contains("vrc.v_")));
            if (bakedVisemes)
                Debug.LogWarning("[TripoFaceRig] A clip in the controller still animates vrc.v_* " +
                                 "shapes and will fight the cue player. Set that layer's weight to " +
                                 "0, or use the ambient face clip that carries only blinks and gaze.");
        }

        /// <summary>
        /// Regenerates the cue file from the dialogue clip, so the A/B test uses
        /// cues produced exactly the way the runtime path will produce them.
        /// </summary>
        [MenuItem("Tools/Tripo Face Rig/10c. Regenerate Rhubarb Cues")]
        public static void RegenerateCues()
        {
            string exe = ResolveRhubarb();
            if (!File.Exists(exe))
            {
                Debug.LogError($"[TripoFaceRig] rhubarb.exe not found at {exe}.");
                return;
            }

            string wav = Path.GetFullPath(DialogueAsset);
            string outPath = Path.GetFullPath(CuesAsset);
            // -d <text> goes here once the LLM's line is available; Rhubarb uses
            // it to constrain recognition. Measured influence is real but modest:
            // a wrong transcript moved 1 of 91 cues on the reference clip.
            var psi = new System.Diagnostics.ProcessStartInfo(exe,
                $"-q -r pocketSphinx -f json -o \"{outPath}\" \"{wav}\"")
            {
                UseShellExecute = false,
                RedirectStandardError = true,
                CreateNoWindow = true,
            };

            var sw = System.Diagnostics.Stopwatch.StartNew();
            using (var p = System.Diagnostics.Process.Start(psi))
            {
                string err = p.StandardError.ReadToEnd();
                p.WaitForExit();
                sw.Stop();
                if (p.ExitCode != 0)
                {
                    Debug.LogError($"[TripoFaceRig] rhubarb failed ({p.ExitCode}): {err}");
                    return;
                }
            }
            AssetDatabase.ImportAsset(CuesAsset);
            Debug.Log($"[TripoFaceRig] Cues regenerated in {sw.ElapsedMilliseconds}ms -> {CuesAsset}. " +
                      "That figure is the latency the runtime TTS path will pay per line.");
        }

        private static string ResolveRhubarb()
        {
            string exe = Environment.GetEnvironmentVariable("RHUBARB_PATH");
            if (File.Exists(exe)) return Path.GetFullPath(exe);
            string name = Application.platform == RuntimePlatform.WindowsEditor ? "rhubarb.exe" : "rhubarb";
            foreach (string folder in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator))
            {
                string candidate = Path.Combine(folder.Trim('"'), name);
                if (File.Exists(candidate)) return candidate;
            }
            return "";
        }

        /// <summary>
        /// Flips between independent ARKit channels with coarticulation and the
        /// original eight lumped visemes, so the two can be compared on the same
        /// line rather than argued about.
        /// </summary>
        [MenuItem("Tools/Tripo Face Rig/10d. Toggle Articulation (ARKit <-> Lumped)")]
        public static void ToggleArticulation()
        {
            var go = GameObject.Find(CharacterName);
            if (go == null) { Debug.LogError($"[TripoFaceRig] No '{CharacterName}' in the scene."); return; }
            var player = go.GetComponent<RhubarbVisemePlayer>();
            if (player == null) { Debug.LogError("[TripoFaceRig] Run step 10 first."); return; }

            if (Application.isPlaying)
            {
                // SetMode clears the shapes the old mode owned; assigning the
                // serialized field alone would strand them mid-pose.
                var next = (RhubarbVisemePlayer.Articulation)(
                    ((int)GetMode(player) + 1) % 2);
                player.SetMode(next);
                Debug.Log($"[TripoFaceRig] Articulation -> {next} (live).");
                return;
            }

            var so = new SerializedObject(player);
            var mode = so.FindProperty("mode");
            mode.enumValueIndex = (mode.enumValueIndex + 1) % 2;
            so.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(player);
            UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(go.scene);
            Debug.Log($"[TripoFaceRig] Articulation -> " +
                      $"{(RhubarbVisemePlayer.Articulation)mode.enumValueIndex}. Press Play.");
        }

        private static RhubarbVisemePlayer.Articulation GetMode(RhubarbVisemePlayer p)
        {
            var so = new SerializedObject(p);
            return (RhubarbVisemePlayer.Articulation)so.FindProperty("mode").enumValueIndex;
        }
    }
}
