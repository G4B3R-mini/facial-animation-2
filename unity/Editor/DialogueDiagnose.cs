// Reports why dialogue audio is or is not playing.
//
//   Tools > Tripo Face Rig > 9. Diagnose Dialogue
//
// Written because "the dialogue isn't playing" has at least a dozen causes and
// most of them are silent: nothing logs a warning when the Game view's mute
// button is on, when there is no AudioListener, when volume is 0, or when a 3D
// AudioSource is simply too far from the listener to be audible.
//
// Works in Edit mode (serialized state) and in Play mode (live state, which also
// reports whether the source is actually playing and how loud uLipSync thinks it
// is). Run it in BOTH: several of these only differ once Play starts.
using System.Linq;
using System.Reflection;
using System.Text;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

namespace TripoFaceRig.EditorTools
{
    public static class HelenDialogueDiagnose
    {
        private const string CharacterName = "helen";

        [MenuItem("Tools/Tripo Face Rig/9. Diagnose Dialogue")]
        public static void Run()
        {
            var sb = new StringBuilder();
            sb.AppendLine("===== TripoFaceRig dialogue diagnosis =====");
            sb.AppendLine("mode: " + (Application.isPlaying ? "PLAY" : "EDIT"));

            // ---- global audio, the silent killers
            bool masterMute = false;
            var mm = typeof(EditorUtility).GetProperty("audioMasterMute",
                BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
            if (mm != null) masterMute = (bool)mm.GetValue(null);
            sb.AppendLine($"[global] Game-view Mute Audio: {(masterMute ? "ON  <-- silences everything" : "off")}");
            sb.AppendLine($"[global] AudioListener.volume: {AudioListener.volume}" +
                          (AudioListener.volume <= 0.001f ? "  <-- silent" : ""));
            sb.AppendLine($"[global] AudioListener.pause: {AudioListener.pause}" +
                          (AudioListener.pause ? "  <-- silent" : ""));

            var listeners = Object.FindObjectsByType<AudioListener>(
                FindObjectsInactive.Include, FindObjectsSortMode.None);
            int activeListeners = listeners.Count(l => l.isActiveAndEnabled);
            sb.AppendLine($"[global] AudioListeners: {listeners.Length} in scene, {activeListeners} active" +
                          (activeListeners == 0 ? "  <-- NO LISTENER, nothing is audible"
                                                : activeListeners > 1 ? "  <-- more than one, Unity warns and uses one" : ""));

            var go = GameObject.Find(CharacterName);
            if (go == null)
            {
                sb.AppendLine($"[fatal] No GameObject named '{CharacterName}' in the open scene.");
                Debug.Log(sb.ToString());
                return;
            }
            sb.AppendLine($"[object] '{go.name}' active={go.activeInHierarchy}");

            // ---- audio source
            var src = go.GetComponent<AudioSource>();
            if (src == null)
            {
                sb.AppendLine("[fatal] No AudioSource on helen.");
            }
            else
            {
                sb.AppendLine($"[audio] enabled={src.enabled} mute={src.mute}" +
                              (src.mute ? "  <-- muted" : ""));
                sb.AppendLine($"[audio] clip={(src.clip != null ? src.clip.name + " (" + src.clip.length.ToString("0.00") + "s)" : "NONE  <-- nothing to play")}");
                sb.AppendLine($"[audio] volume={src.volume}" + (src.volume <= 0.001f ? "  <-- silent" : ""));
                sb.AppendLine($"[audio] playOnAwake={src.playOnAwake} loop={src.loop} pitch={src.pitch}");
                sb.AppendLine($"[audio] spatialBlend={src.spatialBlend} " +
                              (src.spatialBlend > 0.01f
                                  ? $"(3D) min={src.minDistance} max={src.maxDistance} rolloff={src.rolloffMode}"
                                  : "(2D, distance does not matter)"));
                sb.AppendLine($"[audio] mixerGroup={(src.outputAudioMixerGroup != null ? src.outputAudioMixerGroup.name : "none (direct)")}");

                if (src.spatialBlend > 0.01f && activeListeners > 0)
                {
                    var l = listeners.First(x => x.isActiveAndEnabled);
                    float d = Vector3.Distance(l.transform.position, src.transform.position);
                    sb.AppendLine($"[audio] listener distance={d:0.00} vs maxDistance={src.maxDistance}" +
                                  (d > src.maxDistance ? "  <-- OUT OF RANGE, inaudible" : ""));
                }

                if (Application.isPlaying)
                    sb.AppendLine($"[audio] isPlaying={src.isPlaying} time={src.time:0.00}" +
                                  (!src.isPlaying ? "  <-- not playing right now" : ""));
            }

            // ---- who is supposed to start it
            ReportBehaviour(sb, go, "FacePerformancePlayer",
                new[] { "playOnStart", "stateName", "faceLayer", "audioOffset", "waitForWarmFrames" });
            ReportBehaviour(sb, go, "SpeechGestureDriver",
                new[] { "speakOnStart", "testClip", "gestureCount" });

            var cal = go.GetComponents<MonoBehaviour>()
                .FirstOrDefault(c => c != null && c.GetType().Name == "LipSyncAutoCalibrate");
            if (cal != null)
                sb.AppendLine($"[calibrate] LipSyncAutoCalibrate is STILL ATTACHED, enabled={cal.enabled}" +
                              (cal.enabled
                                  ? "  <-- it seizes the AudioSource on Start and replays the calibration clip. Disable it."
                                  : ""));

            // ---- animator / face layer
            var an = go.GetComponentInChildren<Animator>();
            if (an == null) sb.AppendLine("[anim] no Animator.");
            else
            {
                var rac = an.runtimeAnimatorController;
                sb.AppendLine($"[anim] controller={(rac != null ? rac.name : "NONE  <-- nothing animates")}");
                var ctrl = rac as AnimatorController;
                if (ctrl == null && rac != null)
                    ctrl = AssetDatabase.LoadAssetAtPath<AnimatorController>(AssetDatabase.GetAssetPath(rac));
                if (ctrl != null)
                {
                    for (int i = 0; i < ctrl.layers.Length; i++)
                    {
                        float w = Application.isPlaying ? an.GetLayerWeight(i) : ctrl.layers[i].defaultWeight;
                        sb.AppendLine($"[anim] layer {i} '{ctrl.layers[i].name}' weight={w} " +
                                      $"states=[{string.Join(", ", ctrl.layers[i].stateMachine.states.Select(s => s.state.name))}]");
                    }
                    var fpp = go.GetComponents<MonoBehaviour>()
                        .FirstOrDefault(c => c != null && c.GetType().Name == "FacePerformancePlayer");
                    if (fpp != null)
                    {
                        var so = new SerializedObject(fpp);
                        string want = so.FindProperty("stateName").stringValue;
                        int layer = so.FindProperty("faceLayer").intValue;
                        if (!string.IsNullOrEmpty(want))
                        {
                            bool ok = layer >= 0 && layer < ctrl.layers.Length &&
                                      ctrl.layers[layer].stateMachine.states.Any(s => s.state.name == want);
                            sb.AppendLine($"[anim] FacePerformancePlayer wants state '{want}' on layer {layer}: " +
                                          (ok ? "found" : "NOT FOUND  <-- the controller was rebuilt and renamed it"));
                        }
                    }
                }
            }

            // ---- lipsync
            var uls = go.GetComponentsInChildren<MonoBehaviour>(true)
                .FirstOrDefault(c => c != null && c.GetType().Name == "uLipSync");
            if (uls == null) sb.AppendLine("[lipsync] no uLipSync component.");
            else
            {
                sb.AppendLine($"[lipsync] uLipSync enabled={uls.enabled}");
                var prof = uls.GetType().GetField("profile")?.GetValue(uls);
                if (prof == null) sb.AppendLine("[lipsync] profile: NONE  <-- cannot classify anything");
                else
                {
                    var names = (string[])prof.GetType().GetMethod("GetPhonemeNames").Invoke(prof, null);
                    var mfccs = prof.GetType().GetField("mfccs").GetValue(prof) as System.Collections.IList;
                    var report = new System.Collections.Generic.List<string>();
                    for (int i = 0; i < names.Length; i++)
                    {
                        bool trained = false;
                        var d = mfccs[i];
                        var list = d.GetType().GetField("mfccCalibrationDataList").GetValue(d) as System.Collections.IEnumerable;
                        foreach (var e in list)
                        {
                            var arr = e.GetType().GetField("array").GetValue(e) as float[];
                            if (arr != null && arr.Any(v => Mathf.Abs(v) > 1e-9f)) { trained = true; break; }
                        }
                        report.Add(names[i] + (trained ? "" : "(UNTRAINED!)"));
                    }
                    sb.AppendLine($"[lipsync] phonemes: {string.Join(", ", report)}");
                    if (report.Any(r => r.Contains("UNTRAINED")))
                        sb.AppendLine("[lipsync]   <-- an untrained phoneme suppresses every other shape. Run step 6.");
                }
            }

            var bsc = go.GetComponentsInChildren<MonoBehaviour>(true)
                .FirstOrDefault(c => c != null && c.GetType().Name == "uLipSyncBlendShape");
            if (bsc != null)
            {
                var t = bsc.GetType();
                var smr = t.GetField("skinnedMeshRenderer").GetValue(bsc) as SkinnedMeshRenderer;
                sb.AppendLine($"[lipsync] blendshape target={(smr != null ? smr.name : "NONE")} " +
                              $"usePhonemeBlend={t.GetField("usePhonemeBlend").GetValue(bsc)} " +
                              $"minVolume={t.GetField("minVolume").GetValue(bsc)} " +
                              $"maxVolume={t.GetField("maxVolume").GetValue(bsc)}");
                var shapes = t.GetField("blendShapes").GetValue(bsc) as System.Collections.IList;
                var bad = new System.Collections.Generic.List<string>();
                foreach (var s in shapes)
                {
                    var st = s.GetType();
                    string ph = (string)st.GetField("phoneme").GetValue(s);
                    int idx = (int)st.GetField("index").GetValue(s);
                    if (idx < 0) bad.Add(ph);
                }
                sb.AppendLine($"[lipsync] {shapes.Count} shapes mapped" +
                              (bad.Count > 0 ? $", UNBOUND: {string.Join(", ", bad)}  <-- index -1" : ", all bound"));
            }

            sb.AppendLine("==========================================");
            Debug.Log(sb.ToString());
        }

        private static void ReportBehaviour(StringBuilder sb, GameObject go, string typeName, string[] fields)
        {
            var c = go.GetComponents<MonoBehaviour>()
                .FirstOrDefault(x => x != null && x.GetType().Name == typeName);
            if (c == null) { sb.AppendLine($"[{typeName}] NOT PRESENT"); return; }

            var so = new SerializedObject(c);
            var parts = new System.Collections.Generic.List<string> { "enabled=" + c.enabled };
            foreach (var f in fields)
            {
                var pr = so.FindProperty(f);
                if (pr == null) { parts.Add(f + "=?"); continue; }
                string v;
                switch (pr.propertyType)
                {
                    case SerializedPropertyType.Boolean: v = pr.boolValue.ToString(); break;
                    case SerializedPropertyType.Integer: v = pr.intValue.ToString(); break;
                    case SerializedPropertyType.Float: v = pr.floatValue.ToString(); break;
                    case SerializedPropertyType.String: v = "'" + pr.stringValue + "'"; break;
                    case SerializedPropertyType.ObjectReference:
                        v = pr.objectReferenceValue != null ? pr.objectReferenceValue.name : "NONE"; break;
                    default: v = pr.propertyType.ToString(); break;
                }
                parts.Add(f + "=" + v);
            }
            sb.AppendLine($"[{typeName}] {string.Join(" ", parts)}");
        }
    }
}
