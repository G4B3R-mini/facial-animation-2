// Builds the speech-driven Animator for Helen and wires the runtime drivers.
//
//   Tools > Tripo Face Rig > 4. Build Speech-Driven Animator
//
// Structure, and why:
//
//   Layer 0 "Body"    Idle  <->  Talk_0..N
//                     Speaking picks talking vs idle. The Gesture trigger, which
//                     the analyser only fires near a PHRASE START, re-picks which
//                     talking loop plays. So variation lands on phrase boundaries
//                     instead of mid-word, which is what stops it reading random.
//
//   Layer 1 "Face"    her baked facial performance, masked to the Head.
//
// Gestures switch the base loop rather than layering additively on purpose: the
// available clips are all full-body talking loops, and stacking one over another
// fights for the same bones. Once there is a calm idle plus SHORT upper-body
// gesture clips, this should become an additive upper-body layer instead - the
// SpeechGestureDriver contract does not change, only the controller.
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

namespace TripoFaceRig.EditorTools
{
    public static class HelenSpeechAnimatorSetup
    {
        private const string HelenFbx = "Assets/Town/helen.fbx";
        private const string MixamoDir = "Assets/Animations/Mixamo";
        private const string MaskPath = "Assets/Animations/HelenFaceMask.mask";
        private const string ControllerPath = "Assets/Animations/HelenSpeech.controller";
        private const string CharacterName = "helen";

        [MenuItem("Tools/Tripo Face Rig/4. Build Speech-Driven Animator")]
        public static void Build()
        {
            var bodyClips = AssetDatabase.FindAssets("t:AnimationClip", new[] { MixamoDir })
                .Select(AssetDatabase.GUIDToAssetPath)
                .SelectMany(p => AssetDatabase.LoadAllAssetsAtPath(p).OfType<AnimationClip>())
                .Where(c => !c.name.StartsWith("__preview__"))
                .OrderBy(c => c.name)
                .ToList();
            if (bodyClips.Count == 0)
            {
                Debug.LogError($"[TripoFaceRig] No body clips in {MixamoDir}. Run step 1 first.");
                return;
            }

            var faceClip = AssetDatabase.LoadAllAssetsAtPath(HelenFbx)
                .OfType<AnimationClip>()
                .Where(c => !c.name.StartsWith("__preview__"))
                .OrderByDescending(c => c.length)
                .FirstOrDefault();
            if (faceClip == null)
            {
                Debug.LogError($"[TripoFaceRig] No face clip inside {HelenFbx}.");
                return;
            }

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

            Directory.CreateDirectory(Path.GetDirectoryName(ControllerPath));
            var ctrl = AnimatorController.CreateAnimatorControllerAtPath(ControllerPath);
            ctrl.AddParameter("Speaking", AnimatorControllerParameterType.Bool);
            ctrl.AddParameter("SpeechLevel", AnimatorControllerParameterType.Float);
            ctrl.AddParameter("GestureIndex", AnimatorControllerParameterType.Int);
            ctrl.AddParameter(new AnimatorControllerParameter
            {
                name = "Gesture",
                type = AnimatorControllerParameterType.Trigger
            });

            // ---------------- layer 0: body
            var l0 = ctrl.layers[0];
            l0.name = "Body";
            ctrl.layers = new[] { l0 };
            var bsm = ctrl.layers[0].stateMachine;

            // The first clip doubles as the idle until a real calm idle exists.
            var idle = bsm.AddState("Idle");
            idle.motion = bodyClips[0];
            idle.writeDefaultValues = true;
            // Foot IK pins the feet to where the animation says they are, instead
            // of letting them slide. Humanoid only, and off by default - which is
            // why the feet drifted even with root motion disabled and all three
            // root axes baked into pose.
            idle.iKOnFeet = true;
            bsm.defaultState = idle;

            var talk = new List<AnimatorState>();
            for (int i = 0; i < bodyClips.Count; i++)
            {
                var st = bsm.AddState("Talk_" + i);
                st.motion = bodyClips[i];
                st.writeDefaultValues = true;
                st.iKOnFeet = true;
                talk.Add(st);

                // Idle -> this talking loop when speech starts and the index matches.
                var enter = idle.AddTransition(st);
                enter.hasExitTime = false;
                enter.duration = 0.25f;
                enter.AddCondition(AnimatorConditionMode.If, 0f, "Speaking");
                enter.AddCondition(AnimatorConditionMode.Equals, i, "GestureIndex");

                // ...and back to idle when it stops.
                var exit = st.AddTransition(idle);
                exit.hasExitTime = false;
                exit.duration = 0.35f;
                exit.AddCondition(AnimatorConditionMode.IfNot, 0f, "Speaking");
            }

            // Gesture re-picks the loop. Only between different states, and only on
            // the trigger, which the analyser fires at phrase starts.
            for (int a = 0; a < talk.Count; a++)
                for (int b = 0; b < talk.Count; b++)
                {
                    if (a == b) continue;
                    var t = talk[a].AddTransition(talk[b]);
                    t.hasExitTime = false;
                    // A longer blend slides less than a short one when the two
                    // clips have the feet planted differently.
                    t.duration = 0.6f;
                    t.AddCondition(AnimatorConditionMode.If, 0f, "Gesture");
                    t.AddCondition(AnimatorConditionMode.Equals, b, "GestureIndex");
                }

            // ---------------- layer 1: face
            ctrl.AddLayer("Face");
            var layers = ctrl.layers;
            var face = layers[1];
            face.avatarMask = mask;
            face.defaultWeight = 1f;
            face.blendingMode = AnimatorLayerBlendingMode.Override;
            layers[1] = face;
            ctrl.layers = layers;

            var fsm = ctrl.layers[1].stateMachine;
            var fst = fsm.AddState(faceClip.name.Replace('|', '_'));
            fst.motion = faceClip;
            fst.writeDefaultValues = true;
            fsm.defaultState = fst;

            EditorUtility.SetDirty(ctrl);
            AssetDatabase.SaveAssets();
            Debug.Log($"[TripoFaceRig] Wrote {ControllerPath}: Idle + {talk.Count} talking loops " +
                      $"on Body, face masked to Head on layer 1. Clips: " +
                      string.Join(", ", bodyClips.Select(c => c.name)));

            Wire(ctrl, bodyClips.Count);
        }

        private static void Wire(AnimatorController ctrl, int gestureCount)
        {
            var go = GameObject.Find(CharacterName);
            if (go == null)
            {
                Debug.LogWarning($"[TripoFaceRig] No '{CharacterName}' in the scene; assign manually.");
                return;
            }

            var animator = go.GetComponentInChildren<Animator>();
            if (animator != null)
            {
                Undo.RecordObject(animator, "Assign speech controller");
                animator.runtimeAnimatorController = ctrl;
                animator.applyRootMotion = false;
                EditorUtility.SetDirty(animator);
            }

            var src = go.GetComponent<AudioSource>();
            if (src == null) src = go.AddComponent<AudioSource>();

            var driver = go.GetComponent<SpeechGestureDriver>();
            if (driver == null) driver = go.AddComponent<SpeechGestureDriver>();
            var so = new SerializedObject(driver);
            so.FindProperty("animator").objectReferenceValue = animator;
            so.FindProperty("audioSource").objectReferenceValue = src;
            so.FindProperty("gestureCount").intValue = Mathf.Max(1, gestureCount);
            so.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(driver);

            // FacePerformancePlayer still owns starting the baked take in sync; the
            // gesture driver reads whatever that AudioSource is playing.
            var player = go.GetComponent<FacePerformancePlayer>();
            if (player != null)
            {
                var pso = new SerializedObject(player);
                pso.FindProperty("faceLayer").intValue = 1;
                pso.ApplyModifiedPropertiesWithoutUndo();
                EditorUtility.SetDirty(player);
            }

            UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(go.scene);
            Debug.Log("[TripoFaceRig] Wired SpeechGestureDriver (gestureCount " + gestureCount +
                      "). For the baked take call DriveExisting() after playback starts; " +
                      "for TTS call Speak(clip) when the audio arrives.");
        }

        [MenuItem("Tools/Tripo Face Rig/4b. Enable Foot IK On Body States")]
        public static void EnableFootIK()
        {
            var ctrl = AssetDatabase.LoadAssetAtPath<AnimatorController>(ControllerPath);
            if (ctrl == null) { Debug.LogError($"[TripoFaceRig] No {ControllerPath}."); return; }
            int n = 0;
            foreach (var layer in ctrl.layers)
                foreach (var cs in layer.stateMachine.states)
                {
                    cs.state.iKOnFeet = true;
                    n++;
                }
            EditorUtility.SetDirty(ctrl);
            AssetDatabase.SaveAssets();
            Debug.Log($"[TripoFaceRig] Foot IK enabled on {n} state(s). " +
                      "If feet still slide, the clips themselves shift weight - " +
                      "a true in-place idle is the fix, not a setting.");
        }
    }
}
