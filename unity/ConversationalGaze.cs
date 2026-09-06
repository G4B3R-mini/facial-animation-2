using UnityEngine;

namespace TripoFaceRig
{
    /// <summary>Phrase-led attention, calibrated eyes and head offsets applied after the torso.</summary>
    [DefaultExecutionOrder(200)]
    public sealed class ConversationalGaze : MonoBehaviour
    {
        [SerializeField] private Transform lookTarget;
        [SerializeField] private SpeechGestureDriver speech;
        [SerializeField] private Animator animator;
        [SerializeField] private SkinnedMeshRenderer[] faceMeshes;
        [Header("Gaze calibration")]
        [SerializeField] private bool useEyeBones = true;
        [SerializeField] private float eyeRangeDeg = 22f;
        [SerializeField] private float eyeUpRangeDeg = 12f;
        [SerializeField] private float eyeDownRangeDeg = 15f;
        [Tooltip("Measured full-weight angles for the blendshape fallback, not anatomical eye limits.")]
        [SerializeField] private Vector3 shapeAngles = new Vector3(7f, 5f, 6f);
        [Range(0f, 1f)] [SerializeField] private float headFollow = 0.50f;
        [SerializeField] private float headRangeDeg = 18f;
        [Range(0f, 1f)] [SerializeField] private float aversionWhileSpeaking = 0.35f;
        [Range(0f, 1f)] [SerializeField] private float aversionWhileListening = 0.12f;
        [Header("Blinks and accents")]
        [Tooltip("Maximum eyelid blendshape weight. Keep below triangle inversion on generated face meshes.")]
        [SerializeField, Range(0.1f, 1f)] private float blinkMax = 0.65f;
        [SerializeField] private float blinkIntervalMin = 2.6f;
        [SerializeField] private float blinkIntervalMax = 5.8f;
        [SerializeField] private float blinkDuration = 0.20f;
        [SerializeField] private float idleNoiseDeg = 0.40f;
        [SerializeField] private float nodDeg = 1.5f;
        [SerializeField] private bool diagnose = true;

        private static readonly string[] Shapes =
        {
            "eyeLookInLeft", "eyeLookOutLeft", "eyeLookUpLeft", "eyeLookDownLeft",
            "eyeLookInRight", "eyeLookOutRight", "eyeLookUpRight", "eyeLookDownRight",
            "eyeBlinkLeft", "eyeBlinkRight"
        };
        private Transform head, leftEye, rightEye;
        private Quaternion semanticHeadOffset;
        private Quaternion headBefore, leftBefore, rightBefore;
        private Quaternion headApplied, leftApplied, rightApplied;
        private bool hasApplied, wasSpeaking, averted;
        private int[][] indices;
        private System.Random random;
        private int lastLine = -1, lastPhrase = -1;
        private Vector2 aversion, saccade, gazeNow, headNow;
        private float nextSaccade, nextBlink, blinkStarted = -99f, nextDecision, aversionEnds;
        private float noiseSeed;
        public float BlinkWeight { get; private set; }
        public Vector2 EyeAngles { get; private set; }
        public bool IsAverted => averted;

        private void Awake()
        {
            if (animator == null) animator = GetComponentInChildren<Animator>();
            if (speech == null) speech = GetComponent<SpeechGestureDriver>();
            if (lookTarget == null && Camera.main != null) lookTarget = Camera.main.transform;
            if (animator != null && animator.isHuman)
            {
                head = animator.GetBoneTransform(HumanBodyBones.Head);
                leftEye = animator.GetBoneTransform(HumanBodyBones.LeftEye);
                rightEye = animator.GetBoneTransform(HumanBodyBones.RightEye);
            }
            if (head == null) { enabled = false; return; }
            // Retains the rig's arbitrary bone axes while defining forward/up in character space.
            semanticHeadOffset = Quaternion.Inverse(head.rotation) * transform.rotation;
            if (faceMeshes == null || faceMeshes.Length == 0)
                faceMeshes = FaceMeshUtil.FindAllDeforming(gameObject, Shapes).ToArray();
            indices = new int[faceMeshes.Length][];
            for (int m = 0; m < faceMeshes.Length; m++)
            {
                indices[m] = new int[Shapes.Length];
                var mesh = faceMeshes[m] != null ? faceMeshes[m].sharedMesh : null;
                for (int s = 0; s < Shapes.Length; s++)
                    indices[m][s] = mesh != null ? mesh.GetBlendShapeIndex(Shapes[s]) : -1;
            }
            ResetAttention();
            if (diagnose) Debug.Log($"[TripoFaceRig] Gaze: {(UsesBones ? "calibrated eye bones" : "7/5/6 degree shape fallback")}, head {head.name}.", this);
        }

        private bool UsesBones => useEyeBones && leftEye != null && rightEye != null;
        private float Range(float min, float max) => Mathf.Lerp(min, max, (float)random.NextDouble());

        private void ResetAttention()
        {
            int seed = speech != null && speech.PerformanceProfile != null ? speech.PerformanceProfile.randomSeed : 731;
            random = new System.Random(seed);
            noiseSeed = Range(1f, 100f);
            float now = Time.time;
            nextBlink = now + Range(blinkIntervalMin, blinkIntervalMax);
            nextSaccade = now + 0.45f;
            nextDecision = now + 1.5f;
            averted = false;
            aversion = saccade = Vector2.zero;
            lastPhrase = -1;
        }

        private void RestoreOffsets()
        {
            if (!hasApplied) return;
            if (head != null && Quaternion.Angle(head.localRotation, headApplied) < 0.001f) head.localRotation = headBefore;
            if (leftEye != null && Quaternion.Angle(leftEye.localRotation, leftApplied) < 0.001f) leftEye.localRotation = leftBefore;
            if (rightEye != null && Quaternion.Angle(rightEye.localRotation, rightApplied) < 0.001f) rightEye.localRotation = rightBefore;
            hasApplied = false;
        }

        private void Update()
        {
            RestoreOffsets();
            float now = Time.time;
            bool speaking = speech != null && speech.IsSpeaking;
            if (speech != null && speech.LineSerial != lastLine)
            {
                lastLine = speech.LineSerial;
                ResetAttention();
            }
            if (wasSpeaking && !speaking)
            {
                averted = false;
                aversion = Vector2.zero;
                nextDecision = now + 1.8f;
                TriggerBlink(now);
            }
            wasSpeaking = speaking;

            if (averted && now >= aversionEnds)
            {
                averted = false;
                aversion = Vector2.zero;
                TriggerBlink(now);
            }
            bool phraseChanged = speaking && speech.PhraseIndex != lastPhrase;
            if (phraseChanged) lastPhrase = speech.PhraseIndex;
            if ((phraseChanged && speech.PhraseIndex > 0 && now >= nextDecision) || (!speaking && now >= nextDecision))
            {
                float chance = speaking ? aversionWhileSpeaking : aversionWhileListening;
                averted = random.NextDouble() < chance;
                aversion = averted ? new Vector2((random.Next(2) == 0 ? -1f : 1f) * Range(8f, 13f), -Range(2f, 4f)) : Vector2.zero;
                aversionEnds = now + Range(0.65f, 1.05f);
                nextDecision = now + (speaking ? 1.2f : Range(2.8f, 5f));
                if (averted) TriggerBlink(now);
            }
            if (now >= nextSaccade)
            {
                saccade = new Vector2(Range(-0.55f, 0.55f), Range(-0.3f, 0.3f));
                nextSaccade = now + Range(0.55f, 1.4f);
            }
            if (now >= nextBlink) TriggerBlink(now);
        }

        private void TriggerBlink(float now)
        {
            if (now - blinkStarted < blinkDuration + 0.15f) return;
            blinkStarted = now;
            nextBlink = now + Range(blinkIntervalMin, blinkIntervalMax);
        }

        private static Vector2 Angles(Vector3 direction)
        {
            direction.Normalize();
            return new Vector2(Mathf.Atan2(direction.x, direction.z) * Mathf.Rad2Deg,
                Mathf.Asin(Mathf.Clamp(direction.y, -1f, 1f)) * Mathf.Rad2Deg);
        }

        private void LateUpdate()
        {
            if (head == null) return;
            float dt = Time.deltaTime;
            headBefore = head.localRotation;
            if (leftEye != null) leftBefore = leftEye.localRotation;
            if (rightEye != null) rightBefore = rightEye.localRotation;
            Vector3 toTarget = lookTarget != null ? lookTarget.position - head.position : transform.forward;
            if (toTarget.sqrMagnitude < 1e-8f) toTarget = transform.forward;
            Vector2 aim = Angles(Quaternion.Inverse(transform.rotation) * toTarget) + aversion + saccade;
            aim.x = Mathf.Clamp(aim.x, -45f, 45f);
            aim.y = Mathf.Clamp(aim.y, -25f, 25f);
            gazeNow = Vector2.Lerp(gazeNow, aim, 1f - Mathf.Exp(-dt / 0.035f));
            Vector3 gazeDirection = transform.rotation * Quaternion.Euler(-gazeNow.y, gazeNow.x, 0f) * Vector3.forward;

            Quaternion frame = head.rotation * semanticHeadOffset;
            Vector2 residual = Angles(Quaternion.Inverse(frame) * gazeDirection);
            Vector2 desired = Vector2.ClampMagnitude(residual * headFollow, headRangeDeg);
            headNow = Vector2.Lerp(headNow, desired, 1f - Mathf.Exp(-dt / 0.26f));
            float t = speech != null && speech.IsSpeaking ? speech.PerformanceTime : Time.time;
            float yawNoise = (Mathf.PerlinNoise(noiseSeed, t * 0.21f) - 0.5f) * 2f * idleNoiseDeg;
            float pitchNoise = (Mathf.PerlinNoise(noiseSeed + 9f, t * 0.16f) - 0.5f) * 2f * idleNoiseDeg;
            float nod = speech != null ? speech.NodPulse * nodDeg : 0f;
            Quaternion offset = Quaternion.Euler(-headNow.y + pitchNoise + nod, headNow.x + yawNoise, 0f);
            head.rotation = frame * offset * Quaternion.Inverse(frame) * head.rotation;

            // Compute the remaining aim AFTER all torso, animation and head offsets.
            frame = head.rotation * semanticHeadOffset;
            residual = Angles(Quaternion.Inverse(frame) * gazeDirection);
            EyeAngles = new Vector2(Mathf.Clamp(residual.x, -eyeRangeDeg, eyeRangeDeg),
                Mathf.Clamp(residual.y, -eyeDownRangeDeg, eyeUpRangeDeg));
            if (UsesBones)
            {
                Quaternion eyes = frame * Quaternion.Euler(-EyeAngles.y, EyeAngles.x, 0f) * Quaternion.Inverse(frame);
                leftEye.rotation = eyes * leftEye.rotation;
                rightEye.rotation = eyes * rightEye.rotation;
            }
            float u = (Time.time - blinkStarted) / Mathf.Max(0.12f, blinkDuration);
            float blinkEnvelope = u < 0f || u >= 1f ? 0f : u < 0.225f ? Mathf.SmoothStep(0f, 1f, u / 0.225f)
                : u < 0.425f ? 1f : 1f - Mathf.SmoothStep(0f, 1f, (u - 0.425f) / 0.575f);
            BlinkWeight = blinkEnvelope * blinkMax;
            float h = UsesBones ? 0f : Mathf.Clamp(EyeAngles.x / Mathf.Max(1f, shapeAngles.x), -1f, 1f);
            float v = UsesBones ? 0f : Mathf.Clamp(EyeAngles.y / Mathf.Max(1f, EyeAngles.y >= 0f ? shapeAngles.y : shapeAngles.z), -1f, 1f);
            for (int m = 0; m < faceMeshes.Length; m++)
            {
                Set(m, 0, Mathf.Max(0f, h)); Set(m, 1, Mathf.Max(0f, -h));
                Set(m, 4, Mathf.Max(0f, -h)); Set(m, 5, Mathf.Max(0f, h));
                Set(m, 2, Mathf.Max(0f, v)); Set(m, 6, Mathf.Max(0f, v));
                Set(m, 3, Mathf.Max(0f, -v)); Set(m, 7, Mathf.Max(0f, -v));
                Set(m, 8, BlinkWeight); Set(m, 9, BlinkWeight);
            }
            headApplied = head.localRotation;
            if (leftEye != null) leftApplied = leftEye.localRotation;
            if (rightEye != null) rightApplied = rightEye.localRotation;
            hasApplied = true;
        }

        private void Set(int mesh, int shape, float value)
        {
            if (faceMeshes[mesh] != null && indices[mesh][shape] >= 0)
                faceMeshes[mesh].SetBlendShapeWeight(indices[mesh][shape], Mathf.Clamp01(value) * 100f);
        }

        private void OnDisable()
        {
            RestoreOffsets();
            if (indices == null) return;
            for (int m = 0; m < indices.Length; m++)
                for (int s = 0; s < Shapes.Length; s++) Set(m, s, 0f);
        }
    }
}
