// Rebuilds the body as a calm idle with an additive gesture layer.
//
//   Tools > Tripo Face Rig > 13. Use Subtle Body Layer
//
// Replaces the Idle <-> Talk_N arrangement from step 8. That one swapped whole
// 15-32s Chatting performances as the BASE pose, so she performed continuously
// whether the line warranted it or not, and the base pose changed underneath her
// feet on every switch.
//
// Here layer 0 is one calm idle that never changes, and gesture rides on top as
// an additive layer whose weight follows her speaking volume at runtime. Silence
// returns her to the idle rather than to another performance.
//
// The mask covers torso, arms and fingers. Not the head - ConversationalGaze owns
// that, and two systems rotating one bone fight. Not the legs - that is what kept
// the feet planted.
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

namespace TripoFaceRig.EditorTools
{
    public static class HelenSubtleBodySetup
    {
        private const string PackDir = "Assets/Social Animations/Animations";
        private const string IdleFbx =
            "Assets/Kevin Iglesias/Human Animations/Animations/Female/Idles/HumanF@Idle01.fbx";
        private const string HelenFbx = "Assets/Town/helen.fbx";
        private const string GestureMaskPath = "Assets/Animations/HelenGestureMask.mask";
        private const string FaceMaskPath = "Assets/Animations/HelenFaceMask.mask";
        private const string ControllerPath = "Assets/Animations/HelenSpeech.controller";
        private const string CharacterName = "helen";

        private static readonly string[] GestureClips =
        {
            "Chatting4", "Chatting6", "Chatting7", "Chatting14",
        };

        // Yes / No / Laughing / Shocked are deliberately NOT in the pool.
        //
        // Two reasons, either one sufficient. They are mostly HEAD animation, and
        // the gesture mask excludes the head so ConversationalGaze can own it -
        // so a nod would arrive gutted, carrying only its shoulders. And they are
        // SEMANTIC: a nod means agreement. Firing one from a volume-driven random
        // pool would have her agreeing with herself mid-sentence, which is worse
        // than not gesturing at all - wrong meaning reads far worse than no
        // meaning.
        //
        // They belong to a later intent channel, where the LLM says what the line
        // MEANS and the body answers. Left here as the list that channel wants.
        private static readonly string[] SemanticClips =
        {
            "Yes1", "Yes2", "Yes3", "No1", "No2", "Laughing1", "Laughing2",
        };

        [MenuItem("Tools/Tripo Face Rig/13. Use Subtle Body Layer")]
        public static void Build()
        {
            var go = GameObject.Find(CharacterName);
            if (go == null) { Debug.LogError($"[TripoFaceRig] No '{CharacterName}' in the scene."); return; }

            ConfigureAdditive();

            if (!File.Exists(IdleFbx))
            {
                Debug.LogError($"[TripoFaceRig] No idle at {IdleFbx}. The whole point of this " +
                               "layout is a calm base pose; without one there is nothing to build on.");
                return;
            }
            ConfigureIdle(IdleFbx);
            var idleClip = AssetDatabase.LoadAllAssetsAtPath(IdleFbx).OfType<AnimationClip>()
                .FirstOrDefault(c => !c.name.StartsWith("__preview__"));
            if (idleClip == null) { Debug.LogError("[TripoFaceRig] No clip inside the idle FBX."); return; }

            var gestures = Load(GestureClips);
            if (gestures.Count == 0)
            {
                Debug.LogError($"[TripoFaceRig] No gesture clips found under {PackDir}.");
                return;
            }

            var gestureMask = BuildMask(GestureMaskPath, part =>
                part == AvatarMaskBodyPart.Body ||
                part == AvatarMaskBodyPart.LeftArm || part == AvatarMaskBodyPart.RightArm ||
                part == AvatarMaskBodyPart.LeftFingers || part == AvatarMaskBodyPart.RightFingers);
            var faceMask = BuildMask(FaceMaskPath, part => part == AvatarMaskBodyPart.Head);

            var ctrl = AnimatorController.CreateAnimatorControllerAtPath(ControllerPath);
            ctrl.AddParameter("Speaking", AnimatorControllerParameterType.Bool);
            ctrl.AddParameter("SpeechLevel", AnimatorControllerParameterType.Float);
            ctrl.AddParameter("GestureIndex", AnimatorControllerParameterType.Int);
            ctrl.AddParameter(new AnimatorControllerParameter
            { name = "Gesture", type = AnimatorControllerParameterType.Trigger });

            // ---- layer 0: one calm idle, forever
            var l0 = ctrl.layers[0];
            l0.name = "Body";
            ctrl.layers = new[] { l0 };
            var idleState = ctrl.layers[0].stateMachine.AddState("Idle");
            idleState.motion = idleClip;
            idleState.writeDefaultValues = true;
            idleState.iKOnFeet = true;
            ctrl.layers[0].stateMachine.defaultState = idleState;

            // ---- layer 1: gesture, OVERRIDE not additive
            //
            // Additive was wrong here and looked it. Additive expresses a clip as a
            // delta from a reference pose, which is right for animation authored AS
            // an offset - breathing, a lean, a weapon recoil. These are 15-32s
            // full-body performances, so their delta from frame 0 is enormous and
            // arbitrary, and adding it to an idle sums two full-body motions into
            // poses no arm can reach.
            //
            // Override with a mask cannot do that: at weight w the upper body is
            // simply a blend between the idle's arms and the gesture's arms, and
            // every intermediate pose is a real pose. This is how talking overlays
            // are normally built.
            ctrl.AddLayer("Gesture");
            var layers = ctrl.layers;
            layers[1].avatarMask = gestureMask;
            layers[1].blendingMode = AnimatorLayerBlendingMode.Override;
            layers[1].defaultWeight = 0f;   // SubtleBodyDriver drives this from volume
            ctrl.layers = layers;

            var gsm = ctrl.layers[1].stateMachine;
            var idleGesture = gsm.AddState("NoGesture");
            // NOT an empty state. On an override layer an empty state with write
            // defaults on drives the masked bones to their DEFAULT values, which is
            // roughly the bind pose - so every fade to silence yanked her arms
            // toward a T-pose. Holding the same idle here makes the fade a no-op.
            idleGesture.motion = idleClip;
            idleGesture.writeDefaultValues = false;
            gsm.defaultState = idleGesture;

            var states = new List<AnimatorState>();
            for (int i = 0; i < gestures.Count; i++)
            {
                var st = gsm.AddState("Gesture_" + i);
                st.motion = gestures[i];
                st.writeDefaultValues = false;
                states.Add(st);

                var enter = idleGesture.AddTransition(st);
                enter.hasExitTime = false; enter.duration = 0.75f;
                enter.AddCondition(AnimatorConditionMode.If, 0f, "Speaking");
                enter.AddCondition(AnimatorConditionMode.Equals, i, "GestureIndex");

                var exit = st.AddTransition(idleGesture);
                exit.hasExitTime = false; exit.duration = 0.8f;
                exit.AddCondition(AnimatorConditionMode.IfNot, 0f, "Speaking");
            }
            for (int a = 0; a < states.Count; a++)
                for (int b = 0; b < states.Count; b++)
                {
                    if (a == b) continue;
                    var t = states[a].AddTransition(states[b]);
                    t.hasExitTime = false; t.duration = 0.9f;
                    t.AddCondition(AnimatorConditionMode.If, 0f, "Gesture");
                    t.AddCondition(AnimatorConditionMode.Equals, b, "GestureIndex");
                }

            // ---- layer 2: face, kept for whatever still uses it
            ctrl.AddLayer("Face");
            layers = ctrl.layers;
            layers[2].avatarMask = faceMask;
            // Zero by default: ConversationalGaze and the viseme player own the
            // face at runtime, and a baked clip animating the same shapes fights.
            layers[2].defaultWeight = 0f;
            ctrl.layers = layers;

            var faceClip = AssetDatabase.LoadAllAssetsAtPath(HelenFbx).OfType<AnimationClip>()
                .Where(c => !c.name.StartsWith("__preview__"))
                .OrderByDescending(c => c.length).FirstOrDefault();
            if (faceClip != null)
            {
                var fsm = ctrl.layers[2].stateMachine;
                var fst = fsm.AddState(faceClip.name.Replace('|', '_'));
                fst.motion = faceClip;
                fst.writeDefaultValues = true;
                fsm.defaultState = fst;
            }

            EditorUtility.SetDirty(ctrl);
            AssetDatabase.SaveAssets();

            Wire(go, ctrl, states.Count);

            Debug.Log($"[TripoFaceRig] Held back for a future intent channel (semantic, and " +
                      $"mostly head motion the mask excludes): {string.Join(", ", SemanticClips)}.");
            Debug.Log($"[TripoFaceRig] Body rebuilt: idle '{idleClip.name}' on layer 0, " +
                      $"{states.Count} gestures on an OVERRIDE layer 1 (torso+arms, no head/legs), " +
                      "face on layer 2 at weight 0. Gesture weight follows speaking volume.");
        }

        private static void Wire(GameObject go, AnimatorController ctrl, int gestureCount)
        {
            var an = go.GetComponentInChildren<Animator>();
            if (an != null)
            {
                an.runtimeAnimatorController = ctrl;
                an.applyRootMotion = false;
                EditorUtility.SetDirty(an);
            }

            var driver = go.GetComponent<SubtleBodyDriver>();
            if (driver == null) driver = go.AddComponent<SubtleBodyDriver>();
            var dso = new SerializedObject(driver);
            dso.FindProperty("animator").objectReferenceValue = an;
            dso.FindProperty("speech").objectReferenceValue = go.GetComponent<SpeechGestureDriver>();
            dso.FindProperty("gestureLayer").intValue = 1;
            if (dso.FindProperty("lookTarget").objectReferenceValue == null && Camera.main != null)
                dso.FindProperty("lookTarget").objectReferenceValue = Camera.main.transform;
            dso.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(driver);

            var sgd = go.GetComponent<SpeechGestureDriver>();
            if (sgd != null)
            {
                var so = new SerializedObject(sgd);
                so.FindProperty("gestureCount").intValue = Mathf.Max(1, gestureCount);
                so.ApplyModifiedPropertiesWithoutUndo();
                EditorUtility.SetDirty(sgd);
            }

            UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(go.scene);
        }

        private static List<AnimationClip> Load(string[] names)
        {
            var wanted = new HashSet<string>(names, System.StringComparer.OrdinalIgnoreCase);
            var found = AssetDatabase.FindAssets("t:AnimationClip", new[] { PackDir })
                .Select(AssetDatabase.GUIDToAssetPath)
                .Where(p => wanted.Contains(Path.GetFileNameWithoutExtension(p)))
                .OrderBy(p => p)
                .SelectMany(p => AssetDatabase.LoadAllAssetsAtPath(p).OfType<AnimationClip>())
                .Where(c => !c.name.StartsWith("__preview__"))
                .ToList();
            var missing = names.Where(n => !AssetDatabase.FindAssets("t:AnimationClip", new[] { PackDir })
                .Select(AssetDatabase.GUIDToAssetPath)
                .Any(p => string.Equals(Path.GetFileNameWithoutExtension(p), n,
                                        System.StringComparison.OrdinalIgnoreCase))).ToArray();
            if (missing.Length > 0)
                Debug.LogWarning($"[TripoFaceRig] Not found in the pack: {string.Join(", ", missing)}");
            return found;
        }

        private static AvatarMask BuildMask(string path, System.Func<AvatarMaskBodyPart, bool> active)
        {
            var mask = AssetDatabase.LoadAssetAtPath<AvatarMask>(path);
            if (mask == null)
            {
                mask = new AvatarMask();
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                AssetDatabase.CreateAsset(mask, path);
            }
            foreach (AvatarMaskBodyPart part in System.Enum.GetValues(typeof(AvatarMaskBodyPart)))
            {
                if (part == AvatarMaskBodyPart.LastBodyPart) continue;
                mask.SetHumanoidBodyPartActive(part, active(part));
            }
            EditorUtility.SetDirty(mask);
            return mask;
        }

        /// <summary>
        /// Import settings for the gesture clips. The additive reference pose is
        /// deliberately OFF: the layer is override now, and leaving the flag set
        /// would quietly re-enable the behaviour that made this look wrong.
        /// </summary>
        private static void ConfigureAdditive()
        {
            int n = 0;
            var wanted = new HashSet<string>(GestureClips, System.StringComparer.OrdinalIgnoreCase);
            foreach (var g in AssetDatabase.FindAssets("t:Model", new[] { PackDir }))
            {
                var path = AssetDatabase.GUIDToAssetPath(g);
                if (!wanted.Contains(Path.GetFileNameWithoutExtension(path))) continue;
                var mi = AssetImporter.GetAtPath(path) as ModelImporter;
                if (mi == null) continue;

                mi.animationType = ModelImporterAnimationType.Human;
                mi.materialImportMode = ModelImporterMaterialImportMode.None;
                var clips = mi.defaultClipAnimations;
                for (int i = 0; i < clips.Length; i++)
                {
                    clips[i].loopTime = true;
                    clips[i].hasAdditiveReferencePose = false;
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
            Debug.Log($"[TripoFaceRig] {n} gesture FBX set to Humanoid, looping, root baked.");
        }

        private static void ConfigureIdle(string path)
        {
            var mi = AssetImporter.GetAtPath(path) as ModelImporter;
            if (mi == null) return;
            mi.animationType = ModelImporterAnimationType.Human;
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
        }
    }
}
