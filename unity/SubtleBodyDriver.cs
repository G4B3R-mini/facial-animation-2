using UnityEngine;

namespace TripoFaceRig
{
    /// <summary>
    /// Keeps the body calm and lets gesture ride on top of it.
    ///
    /// The previous arrangement swapped whole-body Chatting takes in and out. That
    /// is why it read as theatrical: those clips are 15-32s performances, authored
    /// to be watched on their own, so the character was always doing a full-body
    /// performance whether or not the line warranted one - and the base pose kept
    /// changing underneath, which is what made the feet argue with the ground.
    ///
    /// Here the base layer holds one calm idle and never changes. Gesture is an
    /// OVERRIDE layer masked to the torso and arms, and its weight follows how
    /// loudly she is actually speaking. Override, not additive: adding a full
    /// performance take to an idle sums two whole-body motions and produces poses
    /// no arm can reach, which is exactly what it looked like. So a quiet aside barely moves her, an
    /// emphatic line gets the full gesture, and silence returns her to the idle
    /// rather than to another performance. Amplitude carrying meaning is most of
    /// what separates subtle from busy.
    ///
    /// The head is deliberately excluded from the mask: ConversationalGaze owns
    /// it, and two systems rotating the same bone fight.
    /// </summary>
    [DefaultExecutionOrder(100)]
    public sealed class SubtleBodyDriver : MonoBehaviour
    {
        [SerializeField] private Animator animator;
        [SerializeField] private SpeechGestureDriver speech;

        [Tooltip("Index of the masked override gesture layer. Set by the setup menu.")]
        [SerializeField] private int gestureLayer = 1;

        [Tooltip("Gesture weight while speaking quietly. Not zero: on an override " +
                 "layer, weight riding up and down from 0 makes the arms slide " +
                 "between two different poses on every syllable, which is the " +
                 "floaty look. Hold a base and modulate around it.")]
        [Range(0f, 1f)] [SerializeField] private float baseGesture = 0.40f;

        [Tooltip("Gesture weight at full speaking volume.")]
        [Range(0f, 1f)] [SerializeField] private float maxGesture = 0.75f;

        [Tooltip("Loudness below this adds nothing on top of the base.")]
        [Range(0f, 1f)] [SerializeField] private float threshold = 0.18f;

        [Tooltip("Seconds for gesture to rise and fall. Slow on purpose: arms have " +
                 "mass, and tracking the envelope closely reads as twitching.")]
        [SerializeField] private float smoothing = 0.55f;

        [Tooltip("Seconds to fade the arms back to the idle when she stops talking.")]
        [SerializeField] private float releaseSeconds = 0.9f;

        [Header("Orientation")]
        [Tooltip("Who she angles herself toward. Empty uses the main camera.")]
        [SerializeField] private Transform lookTarget;

        [Tooltip("Maximum torso yaw toward the listener, degrees. This is the " +
                 "difference between talking AT someone and talking TO them.")]
        [SerializeField] private float torsoTurnDeg = 9f;

        [SerializeField] private bool diagnose = true;

        private Transform chest;
        private float gesture;
        private float turnNow;
        private Quaternion chestRest = Quaternion.identity;
        private Quaternion lastApplied;
        private Quaternion beforeOffset;
        private bool hasApplied;

        private void Awake()
        {
            if (animator == null) animator = GetComponentInChildren<Animator>();
            if (speech == null) speech = GetComponent<SpeechGestureDriver>();
            if (lookTarget == null && Camera.main != null) lookTarget = Camera.main.transform;

            if (animator != null && animator.isHuman)
            {
                chest = animator.GetBoneTransform(HumanBodyBones.UpperChest);
                if (chest == null) chest = animator.GetBoneTransform(HumanBodyBones.Chest);
                if (chest == null) chest = animator.GetBoneTransform(HumanBodyBones.Spine);
            }
            if (chest != null) chestRest = chest.localRotation;

            if (animator != null && gestureLayer >= animator.layerCount)
            {
                Debug.LogWarning($"[TripoFaceRig] No layer {gestureLayer}; gesture disabled. " +
                                 "Run the Subtle Body setup.", this);
                enabled = false;
                return;
            }

            if (diagnose)
                Debug.Log($"[TripoFaceRig] SubtleBodyDriver: gesture layer {gestureLayer}, " +
                          $"torso bone {(chest != null ? chest.name : "NONE")}.", this);
        }

        private void Update()
        {
            // Remove only our previous offset before Animator evaluation, even if the
            // Animator is culled or does not write this bone. Never substitute a bind pose.
            if (hasApplied && chest != null && Quaternion.Angle(chest.localRotation, lastApplied) < 0.001f)
                chest.localRotation = beforeOffset;
            hasApplied = false;
            if (animator == null) return;

            if (speech != null && speech.UsesPerformanceProfile)
            {
                gesture = speech.GestureEnvelope * maxGesture;
                animator.SetLayerWeight(gestureLayer, gesture);
                return;
            }

            bool speaking = speech != null && speech.IsSpeaking;
            float level = speaking ? speech.Level : 0f;

            float want;
            float tau;
            if (speaking)
            {
                float excess = Mathf.Clamp01((level - threshold) / Mathf.Max(0.01f, 1f - threshold));
                // Modulate ABOVE a held base rather than swinging from zero, so
                // volume changes the size of the gesture without restaging it.
                want = Mathf.Lerp(baseGesture, maxGesture, Mathf.Pow(excess, 1.4f));
                tau = smoothing;
            }
            else
            {
                want = 0f;
                tau = releaseSeconds;
            }

            gesture = Mathf.Lerp(gesture, want,
                1f - Mathf.Exp(-Time.deltaTime / Mathf.Max(0.01f, tau)));
            animator.SetLayerWeight(gestureLayer, gesture);
        }

        // LateUpdate so this lands on top of what the Animator wrote.
        private void LateUpdate()
        {
            if (chest == null || lookTarget == null) return;

            // Same accumulation guard as the head: this offset multiplies onto the
            // Animator's output, so if the Animator ever stops writing this bone
            // the multiply compounds every frame.
            beforeOffset = chest.localRotation;

            Vector3 local = transform.InverseTransformPoint(lookTarget.position);
            float yaw = 0f;
            if (local.sqrMagnitude > 1e-6f)
                yaw = Mathf.Atan2(local.x, local.z) * Mathf.Rad2Deg;
            yaw = Mathf.Clamp(yaw, -torsoTurnDeg, torsoTurnDeg);

            // Slower than the head: a torso turn is a commitment, not a glance.
            turnNow = Mathf.Lerp(turnNow, yaw, 1f - Mathf.Exp(-Time.deltaTime / 0.9f));

            chest.localRotation = chest.localRotation * Quaternion.Euler(0f, turnNow, 0f);
            lastApplied = chest.localRotation;
            hasApplied = true;
        }

        private void OnDisable()
        {
            if (hasApplied && chest != null && Quaternion.Angle(chest.localRotation, lastApplied) < 0.001f)
                chest.localRotation = beforeOffset;
            hasApplied = false;
            if (animator != null && gestureLayer >= 0 && gestureLayer < animator.layerCount)
                animator.SetLayerWeight(gestureLayer, 0f);
        }
    }
}
