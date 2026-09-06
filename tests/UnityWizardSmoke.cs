// Copy into an Editor test folder in a Unity project containing Humanoid fixtures.
// Run TripoWizardSmoke.Run via -executeMethod with TRIPO_WIZARD_* environment paths.
using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Animations;
using UnityEditor.SceneManagement;
using UnityEngine;
using TripoFaceRig;
using TripoFaceRig.EditorTools;

public static class TripoWizardSmoke
{
    public static void Run()
    {
        var scene = EditorSceneManager.NewPreviewScene();
        string generated = null;
        AudioImporter audioImporter = null;
        AudioImporterSampleSettings originalAudioSettings = default;
        try
        {
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(Environment.GetEnvironmentVariable("TRIPO_WIZARD_MODEL"));
            var voice = AssetDatabase.LoadAssetAtPath<AudioClip>(Environment.GetEnvironmentVariable("TRIPO_WIZARD_VOICE"));
            audioImporter = AssetImporter.GetAtPath(AssetDatabase.GetAssetPath(voice)) as AudioImporter;
            if (audioImporter) originalAudioSettings = audioImporter.defaultSampleSettings;
            var cues = AssetDatabase.LoadAssetAtPath<TextAsset>(Environment.GetEnvironmentVariable("TRIPO_WIZARD_CUES"));
            var idle = AssetDatabase.LoadAllAssetsAtPath(Environment.GetEnvironmentVariable("TRIPO_WIZARD_IDLE"))
                .OfType<AnimationClip>().First(c => !c.name.StartsWith("__preview__"));
            var motion = AssetDatabase.LoadAllAssetsAtPath(Environment.GetEnvironmentVariable("TRIPO_WIZARD_MOTION"))
                .OfType<AnimationClip>().First(c => !c.name.StartsWith("__preview__"));
            var root = (GameObject)PrefabUtility.InstantiatePrefab(prefab, scene);
            root.name = "WizardValidation_" + Guid.NewGuid().ToString("N");
            var built = CharacterPipelineSetup.Build(root, voice, cues, idle, new[] { motion });
            var animator = built.GetComponentInChildren<Animator>();
            var controller = animator.runtimeAnimatorController as AnimatorController;
            generated = Path.GetDirectoryName(AssetDatabase.GetAssetPath(controller)).Replace('\\', '/');
            Assert(controller.layers.Length == 2, "controller layers");
            Assert(controller.layers[1].blendingMode == AnimatorLayerBlendingMode.Override, "override gesture layer");
            var generatedIdle = controller.layers[0].stateMachine.defaultState.motion as AnimationClip;
            var jawBinding = EditorCurveBinding.FloatCurve("", typeof(Animator), "Jaw Close");
            var neutral = CharacterPipelineSetup.CaptureNeutralJaw(built);
            Assert(AnimationUtility.GetEditorCurve(generatedIdle, jawBinding) != null, "explicit neutral jaw curve");
            Assert(Mathf.Abs(AnimationUtility.GetEditorCurve(generatedIdle, jawBinding).Evaluate(0) - neutral["Jaw Close"]) < 0.001f, "neutral jaw preserved");
            var mask = controller.layers[1].avatarMask;
            Assert(!mask.GetHumanoidBodyPartActive(AvatarMaskBodyPart.Head), "head excluded");
            Assert(!mask.GetHumanoidBodyPartActive(AvatarMaskBodyPart.LeftLeg), "legs excluded");
            Assert(mask.GetHumanoidBodyPartActive(AvatarMaskBodyPart.LeftArm), "arms included");
            var speech = built.GetComponent<SpeechGestureDriver>();
            Assert(speech.PerformanceProfile.gestures.Length == 1 && speech.PerformanceProfile.gestures[0].IsValid, "valid gesture profile");
            Assert(built.GetComponent<RhubarbVisemePlayer>() && built.GetComponent<ConversationalGaze>() &&
                   built.GetComponent<ConversationExpressionDriver>() && built.GetComponent<SubtleBodyDriver>(), "runtime components");
            var configured = new SerializedObject(speech);
            Assert(configured.FindProperty("audioSource").objectReferenceValue == built.GetComponent<AudioSource>(), "shared audio source");
            Assert(configured.FindProperty("animator").objectReferenceValue == animator, "animator reference");
            Debug.Log("UNITY_WIZARD_SMOKE_PASS");
            string report = Environment.GetEnvironmentVariable("TRIPO_WIZARD_REPORT");
            if (!string.IsNullOrEmpty(report)) File.WriteAllText(report, "UNITY_WIZARD_SMOKE_PASS");
        }
        finally
        {
            EditorSceneManager.ClosePreviewScene(scene);
            if (audioImporter) { audioImporter.defaultSampleSettings = originalAudioSettings; audioImporter.SaveAndReimport(); }
            if (generated != null && generated.StartsWith("Assets/TripoFaceRigGenerated/WizardValidation_", StringComparison.Ordinal))
                AssetDatabase.DeleteAsset(generated);
        }
    }
    private static void Assert(bool value, string message) { if (!value) throw new Exception("Wizard smoke: " + message); }
}
