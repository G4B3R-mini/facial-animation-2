using System;
using System.Linq;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEditor.Animations;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace TripoFaceRig.EditorTools
{
    // Generic entrypoint for an agent or a user; no character or asset paths baked in.
    public sealed class CharacterPipelineSetup : EditorWindow
    {
        [SerializeField] private GameObject character;
        [SerializeField] private AudioClip audio;
        [SerializeField] private TextAsset cues;
        [SerializeField] private AnimationClip idle;
        [SerializeField] private List<AnimationClip> gestures = new List<AnimationClip>();
        [SerializeField] private SpeechPerformanceProfile performance;
        [SerializeField] private Transform lookTarget;
        [SerializeField] private bool playOnStart = true;
        [SerializeField] private string rhubarb = "";
        private bool busy;
        private string status;
        private Vector2 scroll;

        [MenuItem("Tools/Tripo Face Rig/Character Pipeline")]
        public static void Open() => GetWindow<CharacterPipelineSetup>("Character Pipeline");

        [InitializeOnLoadMethod]
        private static void FirstInstall()
        {
            string key = "TripoFaceRig.WizardInstalled.1." + Application.dataPath;
            if (Application.isBatchMode || EditorPrefs.GetBool(key)) return;
            EditorPrefs.SetBool(key, true);
            EditorApplication.delayCall += () => { if (!EditorApplication.isPlayingOrWillChangePlaymode) Open(); };
        }

        private void OnGUI()
        {
            scroll = EditorGUILayout.BeginScrollView(scroll);
            EditorGUILayout.LabelField("Speaking Character", EditorStyles.boldLabel);
            character = (GameObject)EditorGUILayout.ObjectField("Model or scene character", character, typeof(GameObject), true);
            audio = (AudioClip)EditorGUILayout.ObjectField("Test voice", audio, typeof(AudioClip), false);
            cues = (TextAsset)EditorGUILayout.ObjectField("Rhubarb JSON (optional)", cues, typeof(TextAsset), false);
            if (!cues)
            {
                rhubarb = EditorGUILayout.TextField("Rhubarb executable", rhubarb);
                if (GUILayout.Button("Browse for Rhubarb")) rhubarb = EditorUtility.OpenFilePanel("Rhubarb executable", "", "");
                EditorGUILayout.HelpBox("Without JSON, setup generates timings from your WAV. Install the full Rhubarb distribution, including res/sphinx.", MessageType.Info);
                if (GUILayout.Button("Download Rhubarb")) Application.OpenURL("https://github.com/DanielSWolf/rhubarb-lip-sync/releases");
            }
            idle = (AnimationClip)EditorGUILayout.ObjectField("Idle animation", idle, typeof(AnimationClip), false);
            EditorGUILayout.LabelField("Speaking animations (Humanoid)");
            EditorGUILayout.HelpBox("Expand an animation FBX in the Project window and drag the clip inside it into a slot. Use idle for resting; add talking/gesture clips below.", MessageType.None);
            for (int i = 0; i < gestures.Count; i++)
            {
                EditorGUILayout.BeginHorizontal();
                gestures[i] = (AnimationClip)EditorGUILayout.ObjectField(gestures[i], typeof(AnimationClip), false);
                if (GUILayout.Button("Remove", GUILayout.Width(65))) { gestures.RemoveAt(i); i--; }
                EditorGUILayout.EndHorizontal();
            }
            if (GUILayout.Button("Add speaking animation")) gestures.Add(null);
            performance = (SpeechPerformanceProfile)EditorGUILayout.ObjectField("Existing performance (optional)", performance, typeof(SpeechPerformanceProfile), false);
            lookTarget = (Transform)EditorGUILayout.ObjectField("Look at (optional)", lookTarget, typeof(Transform), true);
            playOnStart = EditorGUILayout.Toggle("Speak when Play starts", playOnStart);
            EditorGUILayout.HelpBox("Creates and assigns a new idle + upper-body gesture controller, speech profile, mouth, gaze and expression components. Your previous controller asset is kept. Imported models must have a valid Humanoid Avatar.", MessageType.Info);
            using (new EditorGUI.DisabledScope(busy || EditorApplication.isPlaying))
                if (GUILayout.Button(busy ? "Preparing..." : "Create and wire speaking character", GUILayout.Height(34))) BuildFromWindow();
            if (!string.IsNullOrEmpty(status)) EditorGUILayout.HelpBox(status, MessageType.Info);
            EditorGUILayout.EndScrollView();
        }

        private async void BuildFromWindow()
        {
            busy = true;
            try
            {
                ValidateModel(character);
                ValidateMotions(idle, gestures.ToArray(), performance);
                if (!audio) throw new ArgumentException("Assign a test voice.");
                if (!cues)
                {
                    status = "Generating Rhubarb cues...";
                    Repaint();
                    cues = await CharacterRhubarb.Generate(audio, rhubarb);
                }
                character = Build(character, audio, cues, idle, gestures.ToArray(), performance, lookTarget, playOnStart);
                Selection.activeGameObject = character;
                status = "Ready. Save the scene and press Play. Generated controller/profile are in Assets/TripoFaceRigGenerated. Review gesture segment timings in the profile to tune delivery.";
            }
            catch (Exception error) { status = error.Message; Debug.LogException(error); }
            finally { busy = false; Repaint(); }
        }

        private static Animator ValidateModel(GameObject model)
        {
            if (!model) throw new ArgumentException("Assign a model prefab or a scene character.");
            var animator = model.GetComponentInChildren<Animator>(true);
            if (!animator || !animator.avatar || !animator.avatar.isValid || !animator.avatar.isHuman)
                throw new ArgumentException("Set the FBX Rig to Humanoid, Create From This Model, and Apply. Configure its Avatar if invalid.");
            if (FaceMeshUtil.FindAllDeforming(model, "jawOpen").Count == 0)
                throw new ArgumentException("No deforming jawOpen shape found. Enable Import BlendShapes on the FBX.");
            return animator;
        }

        private static void ValidateMotions(AnimationClip idleClip, AnimationClip[] clips, SpeechPerformanceProfile profile)
        {
            if (!idleClip || !idleClip.humanMotion || idleClip.legacy)
                throw new ArgumentException("Assign a Humanoid idle animation (expand an imported animation FBX to select its clip).");
            if (profile != null && (profile.gestures == null || profile.gestures.Length == 0 || profile.gestures.Any(g => !g.IsValid)))
                throw new ArgumentException("Existing performance profile has missing clips or invalid segment timings.");
            var motions = profile ? profile.gestures.Select(g => g.clip) : (clips ?? Array.Empty<AnimationClip>());
            if (motions.Any(c => !c || !c.humanMotion || c.legacy || c.length < 0.1f))
                throw new ArgumentException("Every speaking animation must be a valid Humanoid clip at least 0.1 seconds long.");
            if (profile && profile.gestures.Select(g => g.stateName).Distinct().Count() != profile.gestures.Length)
                throw new ArgumentException("Performance profile state names must be unique.");
        }

        public static GameObject Build(GameObject model, AudioClip voice, TextAsset json,
            AnimationClip idleClip, AnimationClip[] speakingClips, SpeechPerformanceProfile existingProfile = null,
            Transform target = null, bool speakOnStart = true)
        {
            if (EditorApplication.isPlaying) throw new InvalidOperationException("Run character setup in Edit mode.");
            ValidateModel(model);
            ValidateMotions(idleClip, speakingClips, existingProfile);
            if (!voice || !json) throw new ArgumentException("Assign a voice and matching Rhubarb cues.");
            CharacterRhubarb.Validate(json.text, voice.length);
            var root = model;
            if (EditorUtility.IsPersistent(model))
            {
                root = (GameObject)PrefabUtility.InstantiatePrefab(model);
                Undo.RegisterCreatedObjectUndo(root, "Create speaking character");
            }
            Configure(root, voice, json);
            var animator = root.GetComponentInChildren<Animator>();
            var neutralJaw = CaptureNeutralJaw(model);
            string parent = "Assets/TripoFaceRigGenerated";
            if (!AssetDatabase.IsValidFolder(parent)) AssetDatabase.CreateFolder("Assets", "TripoFaceRigGenerated");
            string folder = AssetDatabase.GenerateUniqueAssetPath(parent + "/" + SafeName(root.name));
            AssetDatabase.CreateFolder(parent, Path.GetFileName(folder));
            var profile = existingProfile ? Instantiate(existingProfile) : CreateInstance<SpeechPerformanceProfile>();
            if (!existingProfile)
                profile.gestures = (speakingClips ?? Array.Empty<AnimationClip>()).Select((c, i) => new SpeechPerformanceProfile.GestureSegment {
                    name = c.name, clip = c, stateName = "Gesture" + i, start = 0,
                    accent = Mathf.Min(c.length, 3f) * 0.35f,
                    holdUntil = Mathf.Min(c.length, 3f) * 0.65f, end = Mathf.Min(c.length, 3f)
                }).ToArray();
            AssetDatabase.CreateAsset(profile, folder + "/Performance.asset");
            var mask = new AvatarMask();
            for (int i = 0; i < (int)AvatarMaskBodyPart.LastBodyPart; i++) mask.SetHumanoidBodyPartActive((AvatarMaskBodyPart)i, false);
            foreach (var part in new[] { AvatarMaskBodyPart.Body, AvatarMaskBodyPart.LeftArm, AvatarMaskBodyPart.RightArm, AvatarMaskBodyPart.LeftFingers, AvatarMaskBodyPart.RightFingers })
                mask.SetHumanoidBodyPartActive(part, true);
            // Exclude all explicit transform curves; only Humanoid body muscles drive this layer.
            mask.AddTransformPath(animator.transform, true);
            for (int i = 0; i < mask.transformCount; i++) mask.SetTransformActive(i, false);
            AssetDatabase.CreateAsset(mask, folder + "/UpperBody.mask");
            var controller = AnimatorController.CreateAnimatorControllerAtPath(folder + "/Speaking.controller");
            controller.AddParameter("Speaking", AnimatorControllerParameterType.Bool);
            controller.AddParameter("SpeechLevel", AnimatorControllerParameterType.Float);
            controller.AddParameter("GestureIndex", AnimatorControllerParameterType.Int);
            controller.AddParameter("Gesture", AnimatorControllerParameterType.Trigger);
            controller.AddParameter("GestureTime", AnimatorControllerParameterType.Float);
            // Remove explicit bone/face tracks from copies; imported source clips stay intact.
            Func<AnimationClip, string, bool, AnimationClip> clean = (clip, name, loop) => {
                var copy = Instantiate(clip);
                copy.name = name;
                foreach (var binding in AnimationUtility.GetCurveBindings(copy))
                    if (binding.type != typeof(Animator) || binding.propertyName.Contains("Jaw") || binding.propertyName.Contains("Eye"))
                        AnimationUtility.SetEditorCurve(copy, binding, null);
                foreach (var binding in AnimationUtility.GetObjectReferenceCurveBindings(copy)) AnimationUtility.SetObjectReferenceCurve(copy, binding, null);
                if (loop)
                    foreach (var channel in neutralJaw)
                        AnimationUtility.SetEditorCurve(copy, EditorCurveBinding.FloatCurve("", typeof(Animator), channel.Key),
                            AnimationCurve.Constant(0, Mathf.Max(0.1f, clip.length), channel.Value));
                AnimationUtility.SetAnimationEvents(copy, Array.Empty<AnimationEvent>());
                var settings = AnimationUtility.GetAnimationClipSettings(copy); settings.loopTime = loop;
                AnimationUtility.SetAnimationClipSettings(copy, settings);
                AssetDatabase.CreateAsset(copy, folder + "/" + name + ".anim");
                return copy;
            };
            var idleState = controller.layers[0].stateMachine.AddState("Idle");
            idleState.motion = clean(idleClip, "Idle", true); idleState.iKOnFeet = true; idleState.writeDefaultValues = false;
            controller.layers[0].stateMachine.defaultState = idleState;
            controller.AddLayer("Gesture");
            var layers = controller.layers;
            layers[0].name = "Body"; layers[1].avatarMask = mask;
            layers[1].blendingMode = AnimatorLayerBlendingMode.Override; layers[1].defaultWeight = 0;
            controller.layers = layers;
            var off = layers[1].stateMachine.AddState("NoGesture"); off.writeDefaultValues = false;
            layers[1].stateMachine.defaultState = off;
            for (int i = 0; i < profile.gestures.Length; i++)
            {
                var segment = profile.gestures[i];
                segment.clip = clean(segment.clip, "Speaking" + i, false); profile.gestures[i] = segment;
                var state = layers[1].stateMachine.AddState(segment.stateName);
                state.motion = segment.clip; state.writeDefaultValues = false;
                state.timeParameter = "GestureTime"; state.timeParameterActive = true;
            }
            Undo.RecordObject(animator, "Assign speaking controller");
            animator.runtimeAnimatorController = controller; animator.applyRootMotion = false;
            var speech = root.GetComponent<SpeechGestureDriver>();
            Set(speech, "performanceProfile", profile);
            var so = new SerializedObject(speech);
            so.FindProperty("performanceLayer").intValue = 1;
            so.FindProperty("gestureCount").intValue = profile.gestures.Length;
            so.FindProperty("speakOnStart").boolValue = speakOnStart;
            so.ApplyModifiedProperties();
            var body = Get<SubtleBodyDriver>(root);
            Set(body, "animator", animator); Set(body, "speech", speech); Set(body, "lookTarget", target);
            var bodySettings = new SerializedObject(body); bodySettings.FindProperty("gestureLayer").intValue = 1; bodySettings.ApplyModifiedProperties();
            Set(root.GetComponent<ConversationalGaze>(), "lookTarget", target);
            var importer = AssetImporter.GetAtPath(AssetDatabase.GetAssetPath(voice)) as AudioImporter;
            if (importer)
            {
                var settings = importer.defaultSampleSettings; settings.loadType = AudioClipLoadType.DecompressOnLoad;
                importer.defaultSampleSettings = settings; importer.SaveAndReimport();
            }
            EditorUtility.SetDirty(profile); AssetDatabase.SaveAssets();
            PrefabUtility.RecordPrefabInstancePropertyModifications(animator);
            EditorSceneManager.MarkSceneDirty(root.scene);
            Debug.Log("SPEAKING_CHARACTER_READY: " + root.name + " | " + folder, root);
            return root;
        }

        private static string SafeName(string value)
        {
            foreach (char c in Path.GetInvalidFileNameChars()) value = value.Replace(c, '_');
            return string.IsNullOrWhiteSpace(value) ? "Character" : value;
        }

        public static Dictionary<string, float> CaptureNeutralJaw(GameObject model)
        {
            // Read the imported prefab rest pose, not an Animator's currently sampled pose.
            var source = EditorUtility.IsPersistent(model) ? model : PrefabUtility.GetCorrespondingObjectFromSource(model);
            if (!source) source = model;
            var preview = EditorSceneManager.NewPreviewScene();
            GameObject copy = null;
            try
            {
                copy = Instantiate(source);
                UnityEngine.SceneManagement.SceneManager.MoveGameObjectToScene(copy, preview);
                var animator = copy.GetComponentInChildren<Animator>();
                animator.runtimeAnimatorController = null;
                var pose = new HumanPose();
                using (var handler = new HumanPoseHandler(animator.avatar, animator.transform)) handler.GetHumanPose(ref pose);
                var values = new Dictionary<string, float>();
                for (int i = 0; i < HumanTrait.MuscleCount; i++)
                    if (HumanTrait.MuscleName[i].StartsWith("Jaw", StringComparison.Ordinal)) values[HumanTrait.MuscleName[i]] = pose.muscles[i];
                return values;
            }
            finally { EditorSceneManager.ClosePreviewScene(preview); }
        }

        public static void Configure(GameObject root, AudioClip clip, TextAsset json)
        {
            if (!root || !root.scene.IsValid() || !clip || !json)
                throw new ArgumentException("Supply a scene character, imported voice AudioClip, and Rhubarb JSON TextAsset.");
            CharacterRhubarb.Validate(json.text, clip.length);
            var animator = root.GetComponentInChildren<Animator>();
            if (!animator || !animator.avatar || !animator.avatar.isValid || !animator.avatar.isHuman)
                throw new ArgumentException("Configure the imported model as Humanoid with a valid Avatar first.");
            if (FaceMeshUtil.FindAllDeforming(root, "jawOpen").Count == 0)
                throw new ArgumentException("No deforming jawOpen shape found. Check FBX blendshapes before wiring.");
            Undo.RegisterFullObjectHierarchyUndo(root, "Wire speaking character");
            var source = Get<AudioSource>(root);
            source.clip = clip;
            source.playOnAwake = false;
            source.loop = false;
            var mouth = Get<RhubarbVisemePlayer>(root);
            Set(mouth, "audioSource", source);
            Set(mouth, "cuesJson", json);
            var serializedMouth = new SerializedObject(mouth);
            serializedMouth.FindProperty("targets").arraySize = 0;
            serializedMouth.FindProperty("mode").enumValueIndex = 0;
            serializedMouth.ApplyModifiedProperties();
            var speech = Get<SpeechGestureDriver>(root);
            Set(speech, "audioSource", source);
            Set(speech, "animator", animator);
            Set(speech, "testClip", clip);
            var serializedSpeech = new SerializedObject(speech);
            serializedSpeech.FindProperty("speakOnStart").boolValue = true;
            serializedSpeech.ApplyModifiedProperties();
            var gaze = Get<ConversationalGaze>(root);
            Set(gaze, "animator", animator);
            Set(gaze, "speech", speech);
            var expression = Get<ConversationExpressionDriver>(root);
            Set(expression, "speech", speech);
            Set(expression, "mouth", mouth);
            Set(expression, "gaze", gaze);
            // Older preview players must not write the same channels simultaneously.
            foreach (var component in root.GetComponentsInChildren<MonoBehaviour>(true))
            {
                if (!component) continue;
                var name = component.GetType().Name;
                if (new[] { "SpeechBrowDriver", "FacePerformancePlayer", "TripoFaceExpressionDriver", "uLipSync", "uLipSyncBlendShape" }.Contains(name))
                {
                    Undo.RecordObject(component, "Disable competing face driver");
                    component.enabled = false;
                }
            }
            EditorSceneManager.MarkSceneDirty(root.scene);
            Debug.Log("CHARACTER_PIPELINE_CONFIGURED: " + root.name + ". Enter Play mode; inspect jaw, tongue, blinks, gaze and body. Configuration is not visual approval.", root);
        }

        private static T Get<T>(GameObject root) where T : Behaviour
        {
            var component = root.GetComponent<T>();
            if (!component) component = Undo.AddComponent<T>(root);
            component.enabled = true;
            return component;
        }

        private static void Set(UnityEngine.Object obj, string field, UnityEngine.Object value)
        {
            var serialized = new SerializedObject(obj);
            var property = serialized.FindProperty(field);
            if (property == null) throw new InvalidOperationException("Missing field " + field);
            property.objectReferenceValue = value;
            serialized.ApplyModifiedProperties();
        }
    }
}
