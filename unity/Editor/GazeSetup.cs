// Enables runtime eyes, blinks and head motion.
//
//   Tools > Tripo Face Rig > 12. Enable Conversational Gaze
//
// The ambient face clip bakes blinks and gaze, which cannot react to dialogue
// that does not exist until runtime, and it drives the same eyeLook*/eyeBlink*
// shapes this component does. So the face layer's weight goes to 0: the runtime
// driver takes over the whole job rather than fighting the clip for it.
using System.Linq;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

namespace TripoFaceRig.EditorTools
{
    public static class HelenGazeSetup
    {
        private const string CharacterName = "helen";

        [MenuItem("Tools/Tripo Face Rig/12. Enable Conversational Gaze")]
        public static void Enable()
        {
            var go = GameObject.Find(CharacterName);
            if (go == null) { Debug.LogError($"[TripoFaceRig] No '{CharacterName}' in the scene."); return; }

            var gaze = go.GetComponent<ConversationalGaze>();
            if (gaze == null) gaze = go.AddComponent<ConversationalGaze>();
            gaze.enabled = true;

            var animator = go.GetComponentInChildren<Animator>();
            var so = new SerializedObject(gaze);
            so.FindProperty("animator").objectReferenceValue = animator;
            so.FindProperty("speech").objectReferenceValue = go.GetComponent<SpeechGestureDriver>();
            if (so.FindProperty("lookTarget").objectReferenceValue == null && Camera.main != null)
                so.FindProperty("lookTarget").objectReferenceValue = Camera.main.transform;
            so.FindProperty("faceMeshes").arraySize = 0;   // re-probe by deformation
            so.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(gaze);

            // Silence the baked blinks/gaze so the two do not fight.
            var ctrl = animator != null
                ? animator.runtimeAnimatorController as AnimatorController
                : null;
            if (ctrl == null && animator != null && animator.runtimeAnimatorController != null)
                ctrl = AssetDatabase.LoadAssetAtPath<AnimatorController>(
                    AssetDatabase.GetAssetPath(animator.runtimeAnimatorController));

            if (ctrl != null)
            {
                var layers = ctrl.layers;
                for (int i = 0; i < layers.Length; i++)
                {
                    bool drivesFace = layers[i].stateMachine.states.Any(s =>
                        s.state.motion is AnimationClip c &&
                        AnimationUtility.GetCurveBindings(c).Any(b =>
                            b.propertyName.Contains("eyeBlink") ||
                            b.propertyName.Contains("eyeLook")));
                    if (!drivesFace) continue;
                    layers[i].defaultWeight = 0f;
                    Debug.Log($"[TripoFaceRig] Layer {i} '{layers[i].name}' animates eye shapes; " +
                              "weight set to 0 so the runtime driver owns them.");
                }
                ctrl.layers = layers;
                EditorUtility.SetDirty(ctrl);
                AssetDatabase.SaveAssets();
            }

            if (Camera.main == null)
                Debug.LogWarning("[TripoFaceRig] No MainCamera tag in the scene, so there is nothing " +
                                 "to look at - assign lookTarget by hand or she will stare straight ahead.");

            UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(go.scene);
            Debug.Log("[TripoFaceRig] Conversational gaze enabled: aversion at phrase boundaries, " +
                      "saccades, blinks on gaze shifts, head follows the eyes at 35%. Press Play.");
        }

        [MenuItem("Tools/Tripo Face Rig/12b. Disable Conversational Gaze")]
        public static void Disable()
        {
            var go = GameObject.Find(CharacterName);
            if (go == null) { Debug.LogError($"[TripoFaceRig] No '{CharacterName}' in the scene."); return; }
            var gaze = go.GetComponent<ConversationalGaze>();
            if (gaze != null) gaze.enabled = false;
            Debug.LogWarning("[TripoFaceRig] Gaze disabled. The eye shapes keep whatever value they " +
                             "held; re-enable the baked face layer if you want blinks back.");
            UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(go.scene);
        }
    }
}
