// Builds an AnimatorController for the Helen face rig and wires it onto the
// character in the open scene.
//
// Tools > Tripo Face Rig > Build Helen Face Animator
//
// The FBX imports as Generic (animationType 2), which is what we want for a
// facial test: the baked clip drives the face bones and the blendshape curves
// exactly as authored in Blender, with no Humanoid retargeting in between.
//
// Clip names are discovered from the FBX rather than hardcoded, because Blender
// names its takes from the object/action ("Armature|Scene", "Key.001|Scene",
// ...) and that varies with how the scene was assembled.
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

namespace TripoFaceRig.EditorTools
{
    public static class HelenFaceAnimatorSetup
    {
        private const string FbxPath = "Assets/Town/helen.fbx";
        private const string ControllerPath = "Assets/Animations/HelenFace.controller";
        private const string CharacterName = "helen";

        [MenuItem("Tools/Tripo Face Rig/Build Helen Face Animator")]
        public static void Build()
        {
            var clips = AssetDatabase.LoadAllAssetsAtPath(FbxPath)
                .OfType<AnimationClip>()
                .Where(c => !c.name.StartsWith("__preview__"))
                .OrderByDescending(c => c.length)
                .ToList();

            if (clips.Count == 0)
            {
                Debug.LogError(
                    $"[TripoFaceRig] No AnimationClips inside {FbxPath}. " +
                    "Check the FBX importer: Animation tab -> Import Animation must be ON.");
                return;
            }

            Debug.Log($"[TripoFaceRig] Found {clips.Count} clip(s) in {FbxPath}: " +
                      string.Join(", ", clips.Select(c => $"{c.name} ({c.length:0.00}s)")));

            Directory.CreateDirectory(Path.GetDirectoryName(ControllerPath));
            var controller = AnimatorController.CreateAnimatorControllerAtPath(ControllerPath);
            var sm = controller.layers[0].stateMachine;

            // "Play" drives the whole baked performance; a Speed parameter makes it
            // easy to slow the take down and inspect individual visemes.
            controller.AddParameter("Play", AnimatorControllerParameterType.Bool);
            controller.AddParameter("Speed", AnimatorControllerParameterType.Float);

            var idle = sm.AddState("Idle");
            idle.writeDefaultValues = true;

            var states = new List<AnimatorState>();
            foreach (var clip in clips)
            {
                var st = sm.AddState(SafeName(clip.name));
                st.motion = clip;
                st.speedParameterActive = true;
                st.speedParameter = "Speed";
                st.writeDefaultValues = true;
                states.Add(st);
            }

            // The performance is the DEFAULT state so pressing Play in the editor
            // immediately shows it - this controller exists to eyeball the face.
            // Idle is still reachable by clearing the Play bool.
            var main = states[0];
            sm.defaultState = main;

            var back = main.AddTransition(idle);
            back.hasExitTime = false;
            back.duration = 0f;
            back.AddCondition(AnimatorConditionMode.IfNot, 0f, "Play");

            var toMain = idle.AddTransition(main);
            toMain.hasExitTime = false;
            toMain.duration = 0f;
            toMain.AddCondition(AnimatorConditionMode.If, 0f, "Play");

            // Play defaults true and Speed to 1 so the default state actually runs.
            // controller.parameters returns a COPY, so the array must be assigned
            // back or the defaults are silently discarded.
            var ps = controller.parameters;
            for (int i = 0; i < ps.Length; i++)
            {
                if (ps[i].name == "Play") ps[i].defaultBool = true;
                if (ps[i].name == "Speed") ps[i].defaultFloat = 1f;
            }
            controller.parameters = ps;

            EditorUtility.SetDirty(controller);
            AssetDatabase.SaveAssets();
            AssetDatabase.Refresh();
            Debug.Log($"[TripoFaceRig] Wrote {ControllerPath} with {states.Count} clip state(s).");

            Wire(controller);
        }

        private static void Wire(AnimatorController controller)
        {
            var go = GameObject.Find(CharacterName);
            if (go == null)
            {
                go = Object.FindObjectsByType<Transform>(FindObjectsInactive.Include, FindObjectsSortMode.None)
                    .Select(t => t.gameObject)
                    .FirstOrDefault(g => g.name.ToLowerInvariant().Contains(CharacterName));
            }

            if (go == null)
            {
                Debug.LogWarning(
                    "[TripoFaceRig] Controller built, but no GameObject named " +
                    $"'{CharacterName}' found in the open scene. Drag it onto her Animator manually.");
                return;
            }

            var animator = go.GetComponentInChildren<Animator>();
            if (animator == null)
            {
                animator = go.AddComponent<Animator>();
                Debug.Log($"[TripoFaceRig] Added an Animator to '{go.name}'.");
            }

            Undo.RecordObject(animator, "Assign Helen face controller");
            animator.runtimeAnimatorController = controller;
            animator.applyRootMotion = false;
            EditorUtility.SetDirty(animator);

            // The driver needs every SkinnedMeshRenderer that carries blendshapes.
            var skins = go.GetComponentsInChildren<SkinnedMeshRenderer>(true)
                .Where(s => s.sharedMesh != null && s.sharedMesh.blendShapeCount > 0)
                .ToArray();
            Debug.Log($"[TripoFaceRig] '{go.name}': Animator wired. " +
                      $"{skins.Length} skinned renderer(s) with blendshapes: " +
                      string.Join(", ", skins.Select(s => $"{s.name}({s.sharedMesh.blendShapeCount})")));

            var driver = go.GetComponent<TripoFaceExpressionDriver>();
            if (driver == null)
            {
                driver = go.AddComponent<TripoFaceExpressionDriver>();
                Debug.Log("[TripoFaceRig] Added TripoFaceExpressionDriver. " +
                          "Assign its Renderers array to the list above to drive shapes by name.");
            }

            WireDialogue(go, animator);
            EditorSceneManagerMarkDirty(go);
        }

        private const string DialoguePath = "Assets/Audio/Dialogue/helen_dialogue.wav";

        [MenuItem("Tools/Tripo Face Rig/Wire Helen Dialogue")]
        public static void WireDialogueMenu()
        {
            var go = GameObject.Find(CharacterName);
            if (go == null)
            {
                Debug.LogWarning($"[TripoFaceRig] No '{CharacterName}' in the open scene.");
                return;
            }
            WireDialogue(go, go.GetComponentInChildren<Animator>());
            EditorSceneManagerMarkDirty(go);
        }

        private static void WireDialogue(GameObject go, Animator animator)
        {
            var clip = AssetDatabase.LoadAssetAtPath<AudioClip>(DialoguePath);
            if (clip == null)
            {
                Debug.LogWarning($"[TripoFaceRig] No dialogue clip at {DialoguePath}.");
                return;
            }

            // NOT "GetComponent() ?? AddComponent()": UnityEngine.Object overloads
            // == for fake-null while ?? tests real null, so the coalesce silently
            // yields a fake-null component instead of creating one.
            var src = go.GetComponent<AudioSource>();
            if (src == null) src = go.AddComponent<AudioSource>();
            Undo.RecordObject(src, "Wire Helen dialogue");
            src.clip = clip;
            src.playOnAwake = false;   // FacePerformancePlayer starts it in sync
            src.loop = false;
            src.spatialBlend = 0f;     // 2D for a bench test; raise for in-world audio
            EditorUtility.SetDirty(src);

            var player = go.GetComponent<FacePerformancePlayer>();
            if (player == null) player = go.AddComponent<FacePerformancePlayer>();
            var so = new SerializedObject(player);
            so.FindProperty("animator").objectReferenceValue = animator;
            so.FindProperty("audioSource").objectReferenceValue = src;
            so.FindProperty("playOnStart").boolValue = true;
            so.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(player);

            Debug.Log($"[TripoFaceRig] Dialogue wired: {clip.name} ({clip.length:0.00}s). " +
                      "FacePerformancePlayer starts audio and animation on the same frame.");
        }

        private static void EditorSceneManagerMarkDirty(GameObject go)
        {
            UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(go.scene);
        }

        private static string SafeName(string s)
        {
            foreach (var c in Path.GetInvalidFileNameChars()) s = s.Replace(c, '_');
            return s.Replace('|', '_');
        }

        [MenuItem("Tools/Tripo Face Rig/Report Helen Blendshapes")]
        public static void Report()
        {
            var go = GameObject.Find(CharacterName);
            if (go == null)
            {
                Debug.LogWarning($"[TripoFaceRig] No '{CharacterName}' in the open scene.");
                return;
            }
            foreach (var s in go.GetComponentsInChildren<SkinnedMeshRenderer>(true))
            {
                var m = s.sharedMesh;
                if (m == null || m.blendShapeCount == 0) continue;
                var names = Enumerable.Range(0, m.blendShapeCount).Select(m.GetBlendShapeName);
                Debug.Log($"[TripoFaceRig] {s.name}: {m.blendShapeCount} shapes -> " +
                          string.Join(", ", names.Take(12)) + (m.blendShapeCount > 12 ? " ..." : ""));
            }
        }
    }
}
