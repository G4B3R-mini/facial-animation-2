// Rebuilds Helen's body layer on the Social Animations pack.
//
//   Tools > Tripo Face Rig > 8. Use Social Animations
//
// The pack is already Humanoid (animationType 3), so it retargets onto her
// CC_Base_* rig natively. What it does NOT ship with is root motion baked or
// looping enabled, so both are set here - the same settings that stopped the
// Mixamo clips sliding.
//
// Its Chatting clips are 15-32s performance takes rather than short beats, which
// suits ambient dialogue: a 20s+ loop does not visibly repeat, and swapping
// between fourteen of them at phrase boundaries reads as variation rather than
// as a cycle. The short one-shots (Shocked, Emotion) are reaction beats, not
// conversational gesture, so they are deliberately left out of the talking pool.
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

namespace TripoFaceRig.EditorTools
{
    public static class HelenSocialAnimSetup
    {
        private const string PackDir = "Assets/Social Animations/Animations";
        private const string TalkDir = PackDir + "/Chatting";
        private const string MixamoDir = "Assets/Animations/Mixamo";
        // A real neutral idle, already in the project. Without one, a chatting
        // take stands in and she gesticulates while silent.
        private const string IdleFbx =
            "Assets/Kevin Iglesias/Human Animations/Animations/Female/Idles/HumanF@Idle01.fbx";
        private const string HelenFbx = "Assets/Town/helen.fbx";
        private const string MaskPath = "Assets/Animations/HelenFaceMask.mask";
        private const string ControllerPath = "Assets/Animations/HelenSpeech.controller";
        private const string CharacterName = "helen";

        // Hand-picked for this character. The pack ships 14 Chatting takes but
        // most read wrong for her - edit this list per NPC rather than using all
        // of them, since gesture style is characterisation, not filler.
        // Empty = use every clip in the folder.
        private static readonly string[] TalkClips =
        {
            "Chatting4", "Chatting6", "Chatting7", "Chatting14",
        };

        [MenuItem("Tools/Tripo Face Rig/8. Use Social Animations")]
        public static void Build()
        {
            // Reimport first, then load: see the note on ConfigureOne below.
            ConfigureImports();

            var talk = LoadClips(TalkDir, TalkClips);
            if (talk.Count == 0)
            {
                Debug.LogError($"[TripoFaceRig] No clips under {TalkDir}.");
                return;
            }

            // The pack has no idle. Prefer anything actually named idle, from
            // either source; otherwise fall back to the shortest chatting take and
            // say so, because a chatting clip playing while silent is the reason
            // she gesticulates at nothing.
            // Configure BEFORE loading. SaveAndReimport destroys every object
            // previously loaded from that asset, so a clip fetched first becomes a
            // dangling reference the moment the importer runs.
            if (System.IO.File.Exists(IdleFbx)) ConfigureOne(IdleFbx);

            var idleClip = AssetDatabase.LoadAllAssetsAtPath(IdleFbx)
                .OfType<AnimationClip>()
                .FirstOrDefault(c => !c.name.StartsWith("__preview__"));
            if (idleClip == null)
                idleClip = LoadClips(MixamoDir).Concat(talk)
                    .FirstOrDefault(c => c.name.ToLowerInvariant().Contains("idle"));
            bool realIdle = idleClip != null;
            if (!realIdle) idleClip = talk.OrderBy(c => c.length).First();

            var faceClip = AssetDatabase.LoadAllAssetsAtPath(HelenFbx)
                .OfType<AnimationClip>()
                .Where(c => !c.name.StartsWith("__preview__"))
                .OrderByDescending(c => c.length).FirstOrDefault();

            var mask = AssetDatabase.LoadAssetAtPath<AvatarMask>(MaskPath);
            if (mask == null)
            {
                mask = new AvatarMask();
                foreach (AvatarMaskBodyPart part in System.Enum.GetValues(typeof(AvatarMaskBodyPart)))
                {
                    if (part == AvatarMaskBodyPart.LastBodyPart) continue;
                    mask.SetHumanoidBodyPartActive(part, part == AvatarMaskBodyPart.Head);
                }
                Directory.CreateDirectory(Path.GetDirectoryName(MaskPath));
                AssetDatabase.CreateAsset(mask, MaskPath);
            }

            var ctrl = AnimatorController.CreateAnimatorControllerAtPath(ControllerPath);
            ctrl.AddParameter("Speaking", AnimatorControllerParameterType.Bool);
            ctrl.AddParameter("SpeechLevel", AnimatorControllerParameterType.Float);
            ctrl.AddParameter("GestureIndex", AnimatorControllerParameterType.Int);
            ctrl.AddParameter(new AnimatorControllerParameter
            { name = "Gesture", type = AnimatorControllerParameterType.Trigger });

            var l0 = ctrl.layers[0];
            l0.name = "Body";
            ctrl.layers = new[] { l0 };
            var bsm = ctrl.layers[0].stateMachine;

            var idle = bsm.AddState("Idle");
            idle.motion = idleClip;
            idle.writeDefaultValues = true;
            idle.iKOnFeet = true;
            bsm.defaultState = idle;

            var states = new List<AnimatorState>();
            for (int i = 0; i < talk.Count; i++)
            {
                var st = bsm.AddState("Talk_" + i);
                st.motion = talk[i];
                st.writeDefaultValues = true;
                st.iKOnFeet = true;
                states.Add(st);

                var enter = idle.AddTransition(st);
                enter.hasExitTime = false; enter.duration = 0.35f;
                enter.AddCondition(AnimatorConditionMode.If, 0f, "Speaking");
                enter.AddCondition(AnimatorConditionMode.Equals, i, "GestureIndex");

                var exit = st.AddTransition(idle);
                exit.hasExitTime = false; exit.duration = 0.45f;
                exit.AddCondition(AnimatorConditionMode.IfNot, 0f, "Speaking");
            }

            // Any-state style swapping would need 14x13 transitions; route through
            // the trigger from each state to each other, but with a generous blend
            // so differing foot plants do not snap.
            for (int a = 0; a < states.Count; a++)
                for (int b = 0; b < states.Count; b++)
                {
                    if (a == b) continue;
                    var t = states[a].AddTransition(states[b]);
                    t.hasExitTime = false; t.duration = 0.6f;
                    t.AddCondition(AnimatorConditionMode.If, 0f, "Gesture");
                    t.AddCondition(AnimatorConditionMode.Equals, b, "GestureIndex");
                }

            ctrl.AddLayer("Face");
            var layers = ctrl.layers;
            layers[1].avatarMask = mask;
            layers[1].defaultWeight = 1f;
            layers[1].blendingMode = AnimatorLayerBlendingMode.Override;
            ctrl.layers = layers;
            if (faceClip != null)
            {
                var fsm = ctrl.layers[1].stateMachine;
                var fst = fsm.AddState(faceClip.name.Replace('|', '_'));
                fst.motion = faceClip;
                fst.writeDefaultValues = true;
                fsm.defaultState = fst;
            }

            EditorUtility.SetDirty(ctrl);
            AssetDatabase.SaveAssets();

            var go = GameObject.Find(CharacterName);
            if (go != null)
            {
                var an = go.GetComponentInChildren<Animator>();
                if (an != null) { an.runtimeAnimatorController = ctrl; an.applyRootMotion = false; EditorUtility.SetDirty(an); }
                var sgd = go.GetComponent<SpeechGestureDriver>();
                if (sgd != null)
                {
                    var so = new SerializedObject(sgd);
                    so.FindProperty("gestureCount").intValue = states.Count;
                    so.ApplyModifiedPropertiesWithoutUndo();
                    EditorUtility.SetDirty(sgd);
                }
                UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(go.scene);
            }

            if (TalkClips.Length > 0 && states.Count != TalkClips.Length)
                Debug.LogWarning($"[TripoFaceRig] Asked for {TalkClips.Length} clips but got " +
                                 $"{states.Count}; check the names in TalkClips.");
            Debug.Log($"[TripoFaceRig] Body rebuilt on {states.Count} Chatting takes " +
                      $"({talk.Min(c => c.length):0.0}-{talk.Max(c => c.length):0.0}s), idle = '{idleClip.name}'.");
            if (!realIdle)
                Debug.LogWarning("[TripoFaceRig] No idle clip found, so a CHATTING take is standing " +
                                 "in as the idle - she will gesticulate while silent. Grab a free " +
                                 "Mixamo 'Standing Idle' into Assets/Animations/Mixamo and re-run.");
        }

        private static List<AnimationClip> LoadClips(string dir, string[] only = null)
        {
            if (!Directory.Exists(dir)) return new List<AnimationClip>();
            var paths = AssetDatabase.FindAssets("t:AnimationClip", new[] { dir })
                .Select(AssetDatabase.GUIDToAssetPath);

            // Filter on the FBX FILE name, not the clip name: every clip in this
            // pack is internally called "mixamo.com".
            if (only != null && only.Length > 0)
            {
                var wanted = new HashSet<string>(only, System.StringComparer.OrdinalIgnoreCase);
                paths = paths.Where(p => wanted.Contains(Path.GetFileNameWithoutExtension(p)));
            }

            return paths.OrderBy(p => p)
                .SelectMany(p => AssetDatabase.LoadAllAssetsAtPath(p).OfType<AnimationClip>())
                .Where(c => !c.name.StartsWith("__preview__"))
                .ToList();
        }

        /// <summary>Same import treatment for a single model outside the pack.</summary>
        private static void ConfigureOne(string path)
        {
            var mi = AssetImporter.GetAtPath(path) as ModelImporter;
            if (mi == null) return;
            bool changed = false;
            if (mi.animationType != ModelImporterAnimationType.Human)
            {
                mi.animationType = ModelImporterAnimationType.Human;
                changed = true;
            }
            var clips = mi.defaultClipAnimations;
            for (int i = 0; i < clips.Length; i++)
            {
                clips[i].loopTime = true;
                clips[i].lockRootPositionXZ = true;
                clips[i].keepOriginalPositionXZ = false;
                clips[i].lockRootHeightY = true;
                clips[i].keepOriginalPositionY = false;
                clips[i].heightFromFeet = true;
                clips[i].lockRootRotation = true;
                clips[i].keepOriginalOrientation = false;
            }
            mi.clipAnimations = clips;
            EditorUtility.SetDirty(mi);
            mi.SaveAndReimport();
            Debug.Log($"[TripoFaceRig] Configured idle {Path.GetFileName(path)}" +
                      (changed ? " (switched to Humanoid)." : "."));
        }

        private static void ConfigureImports()
        {
            int n = 0;
            foreach (var g in AssetDatabase.FindAssets("t:Model", new[] { PackDir }))
            {
                var path = AssetDatabase.GUIDToAssetPath(g);
                var mi = AssetImporter.GetAtPath(path) as ModelImporter;
                if (mi == null) continue;

                mi.animationType = ModelImporterAnimationType.Human;
                mi.materialImportMode = ModelImporterMaterialImportMode.None;

                var clips = mi.defaultClipAnimations;
                for (int i = 0; i < clips.Length; i++)
                {
                    clips[i].loopTime = true;
                    // Bake all three root axes into the pose, or she walks away
                    // during a take. Unity serialises these as loopBlend*, not
                    // lockRoot*, which is confusing when reading the .meta.
                    clips[i].lockRootPositionXZ = true;
                    clips[i].keepOriginalPositionXZ = false;
                    clips[i].lockRootHeightY = true;
                    clips[i].keepOriginalPositionY = false;
                    clips[i].heightFromFeet = true;
                    clips[i].lockRootRotation = true;
                    clips[i].keepOriginalOrientation = false;
                }
                mi.clipAnimations = clips;
                EditorUtility.SetDirty(mi);
                mi.SaveAndReimport();
                n++;
            }
            AssetDatabase.Refresh();
            Debug.Log($"[TripoFaceRig] Configured {n} Social Animations FBX: Humanoid, looping, " +
                      "root motion baked into pose.");
        }
    }
}
