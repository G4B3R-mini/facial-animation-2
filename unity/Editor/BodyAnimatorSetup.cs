// Body animation for Helen, in three deliberate steps.
//
//   Tools > Tripo Face Rig > 1. Import Mixamo Animations
//   Tools > Tripo Face Rig > 2. Switch Helen To Humanoid
//   Tools > Tripo Face Rig > 3. Build Body + Face Animator
//
// Staged on purpose. Her body skeleton is CC_Base_* while Mixamo clips are
// mixamorig, so retargeting has to go through Humanoid - and that switch is the
// one change most likely to break the face setup that already works. Doing it
// as its own step means a regression can be attributed to it rather than to the
// controller rebuild.
//
// What Humanoid costs: it drops curves for non-humanoid bones. jaw and
// eye_L/eye_R have optional Humanoid slots and are mapped below. brow_L and
// brow_R have no slot, so bone-driven brow motion is lost - but measured on this
// character the browInnerUp blendshape produces MORE displacement (0.0088) than
// the bones do (0.0066), and blendshape curves are unaffected by Humanoid or by
// avatar masks. Rebuild the face clip with brows on the blendshape to recover it.
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

namespace TripoFaceRig.EditorTools
{
    public static class HelenBodyAnimatorSetup
    {
        private const string HelenFbx = "Assets/Town/helen.fbx";
        private const string MixamoDir = "Assets/Animations/Mixamo";
        private const string MaskPath = "Assets/Animations/HelenFaceMask.mask";
        private const string ControllerPath = "Assets/Animations/HelenBodyFace.controller";
        private const string CharacterName = "helen";

        [MenuItem("Tools/Tripo Face Rig/1. Import Mixamo Animations")]
        public static void ImportMixamo()
        {
            var guids = AssetDatabase.FindAssets("t:Model", new[] { MixamoDir });
            if (guids.Length == 0)
            {
                Debug.LogError($"[TripoFaceRig] No models in {MixamoDir}.");
                return;
            }

            foreach (var g in guids)
            {
                var path = AssetDatabase.GUIDToAssetPath(g);
                var mi = AssetImporter.GetAtPath(path) as ModelImporter;
                if (mi == null) continue;

                mi.animationType = ModelImporterAnimationType.Human;
                mi.avatarSetup = ModelImporterAvatarSetup.CreateFromThisModel;
                mi.importAnimation = true;
                // Mixamo ships animation-only FBXs; importing their (absent)
                // materials just creates clutter. importMaterials was removed in
                // Unity 6; materialImportMode replaces it.
                mi.materialImportMode = ModelImporterMaterialImportMode.None;

                var clips = mi.defaultClipAnimations;
                for (int i = 0; i < clips.Length; i++)
                {
                    clips[i].loopTime = true;

                    // "Bake Into Pose" is lockRoot*; "Based Upon" is keepOriginal*.
                    // Setting only keepOriginalPositionXZ=false leaves XZ root
                    // motion ACTIVE, which is why her feet slid around the floor.
                    // All three axes are baked so an in-place talk loop stays put.
                    clips[i].lockRootPositionXZ = true;      // bake XZ into pose
                    clips[i].keepOriginalPositionXZ = false; // based upon: centre of mass
                    clips[i].lockRootHeightY = true;         // bake Y into pose
                    clips[i].keepOriginalPositionY = false;
                    clips[i].heightFromFeet = true;          // based upon: feet -> grounded
                    clips[i].lockRootRotation = true;        // bake rotation into pose
                    clips[i].keepOriginalOrientation = false;
                }
                mi.clipAnimations = clips;

                EditorUtility.SetDirty(mi);
                mi.SaveAndReimport();
                Debug.Log($"[TripoFaceRig] {Path.GetFileName(path)}: Humanoid, " +
                          $"{clips.Length} clip(s) set looping.");
            }
            AssetDatabase.Refresh();
        }

        [MenuItem("Tools/Tripo Face Rig/2. Switch Helen To Humanoid")]
        public static void SwitchHelenHumanoid()
        {
            var mi = AssetImporter.GetAtPath(HelenFbx) as ModelImporter;
            if (mi == null)
            {
                Debug.LogError($"[TripoFaceRig] {HelenFbx} is not a model asset.");
                return;
            }

            mi.animationType = ModelImporterAnimationType.Human;
            mi.avatarSetup = ModelImporterAvatarSetup.CreateFromThisModel;
            mi.importBlendShapes = true;   // the whole face depends on these
            mi.importAnimation = true;
            EditorUtility.SetDirty(mi);
            mi.SaveAndReimport();

            var avatar = AssetDatabase.LoadAllAssetsAtPath(HelenFbx).OfType<Avatar>().FirstOrDefault();
            if (avatar == null)
            {
                Debug.LogError("[TripoFaceRig] Humanoid import produced no Avatar. " +
                               "Open the Rig tab and check Configure for unmapped required bones.");
                return;
            }

            Debug.Log($"[TripoFaceRig] Helen is Humanoid. Avatar valid: {avatar.isValid}, " +
                      $"human: {avatar.isHuman}.");
            if (!avatar.isValid)
                Debug.LogWarning("[TripoFaceRig] Avatar is INVALID - open Rig > Configure and " +
                                 "map the required bones before continuing.");

            Debug.Log("[TripoFaceRig] In Rig > Configure > Head, map the OPTIONAL slots: " +
                      "Jaw -> 'jaw', Left/Right Eye -> 'eye_L'/'eye_R'. brow_L and brow_R have " +
                      "no Humanoid slot; brow motion must come from the browInnerUp blendshape.");
        }

        [MenuItem("Tools/Tripo Face Rig/3. Build Body + Face Animator")]
        public static void BuildLayered()
        {
            // --- face mask: Head only, so the body layer keeps the rest
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
                Debug.Log($"[TripoFaceRig] Created {MaskPath} (Head only).");
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

            var bodyClips = AssetDatabase.FindAssets("t:AnimationClip", new[] { MixamoDir })
                .Select(AssetDatabase.GUIDToAssetPath)
                .SelectMany(p => AssetDatabase.LoadAllAssetsAtPath(p).OfType<AnimationClip>())
                .Where(c => !c.name.StartsWith("__preview__"))
                .ToList();
            if (bodyClips.Count == 0)
            {
                Debug.LogError($"[TripoFaceRig] No body clips in {MixamoDir}. Run step 1 first.");
                return;
            }
            Debug.Log("[TripoFaceRig] Body clips: " +
                      string.Join(", ", bodyClips.Select(c => $"{c.name} ({c.length:0.0}s)")));

            Directory.CreateDirectory(Path.GetDirectoryName(ControllerPath));
            var ctrl = AnimatorController.CreateAnimatorControllerAtPath(ControllerPath);
            ctrl.AddParameter("BodyClip", AnimatorControllerParameterType.Int);

            // layer 0 = body
            var body = ctrl.layers[0];
            body.name = "Body";
            ctrl.layers = new[] { body };
            var bsm = ctrl.layers[0].stateMachine;
            var bodyStates = new List<AnimatorState>();
            foreach (var c in bodyClips)
            {
                var st = bsm.AddState(Safe(c.name));
                st.motion = c;
                st.writeDefaultValues = true;
                bodyStates.Add(st);
            }
            bsm.defaultState = bodyStates[0];
            for (int i = 1; i < bodyStates.Count; i++)
            {
                var t = bodyStates[0].AddTransition(bodyStates[i]);
                t.hasExitTime = false; t.duration = 0.25f;
                t.AddCondition(AnimatorConditionMode.Equals, i, "BodyClip");
                var back = bodyStates[i].AddTransition(bodyStates[0]);
                back.hasExitTime = false; back.duration = 0.25f;
                back.AddCondition(AnimatorConditionMode.Equals, 0, "BodyClip");
            }

            // layer 1 = face, masked to the head, full weight, override
            ctrl.AddLayer("Face");
            var layers = ctrl.layers;
            var face = layers[1];
            face.avatarMask = mask;
            face.defaultWeight = 1f;
            face.blendingMode = AnimatorLayerBlendingMode.Override;
            layers[1] = face;
            ctrl.layers = layers;

            var fsm = ctrl.layers[1].stateMachine;
            var fst = fsm.AddState(Safe(faceClip.name));
            fst.motion = faceClip;
            fst.writeDefaultValues = true;
            fsm.defaultState = fst;

            EditorUtility.SetDirty(ctrl);
            AssetDatabase.SaveAssets();
            Debug.Log($"[TripoFaceRig] Wrote {ControllerPath}: Body layer " +
                      $"({bodyStates.Count} states) + Face layer (masked to Head, weight 1).");

            var go = GameObject.Find(CharacterName);
            if (go == null)
            {
                Debug.LogWarning($"[TripoFaceRig] No '{CharacterName}' in the scene; assign manually.");
                return;
            }
            var animator = go.GetComponentInChildren<Animator>();
            if (animator != null)
            {
                Undo.RecordObject(animator, "Assign layered controller");
                animator.runtimeAnimatorController = ctrl;
                animator.applyRootMotion = false;
                EditorUtility.SetDirty(animator);
                UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(go.scene);
                Debug.Log("[TripoFaceRig] Assigned to " + go.name +
                          ". Blendshape curves are unaffected by the avatar mask, so the " +
                          "face plays on top of the body regardless of masking.");
            }
        }

        private static string Safe(string s)
        {
            foreach (var c in Path.GetInvalidFileNameChars()) s = s.Replace(c, '_');
            return s.Replace('|', '_');
        }
    }
}
