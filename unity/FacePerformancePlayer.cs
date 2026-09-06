using System.Collections;
using UnityEngine;

namespace TripoFaceRig
{
    /// <summary>
    /// Starts the baked facial performance and its dialogue audio on the same
    /// frame, so the lipsync lands where Rhubarb put it.
    ///
    /// Deliberately does not poll or resync every frame: Animator and AudioSource
    /// both run off the same clock once started, and continuous correction makes
    /// the mouth stutter. If drift shows up over a long take, that is a sample
    /// rate or fps mismatch worth fixing at the source rather than papering over.
    ///
    /// No keyboard input here - the project uses the Input System package, where
    /// legacy Input.GetKeyDown throws. Use the context menu or call Play().
    /// </summary>
    [RequireComponent(typeof(AudioSource))]
    public sealed class FacePerformancePlayer : MonoBehaviour
    {
        [Tooltip("Animator holding the facial performance. Found on this object or a child if empty.")]
        [SerializeField] private Animator animator;

        [Tooltip("Dialogue clip. Must match the audio the Rhubarb cues were generated from.")]
        [SerializeField] private AudioSource audioSource;

        [Tooltip("Animator state to play. Leave empty to use whatever the controller's default state is.")]
        [SerializeField] private string stateName = "";

        [Tooltip("Layer carrying the facial performance. 0 for a face-only controller, 1 for body+face.")]
        [SerializeField] private int faceLayer = 0;

        [Tooltip("Seconds to delay the audio. Positive = audio later. Only needed if the take has lead-in.")]
        [SerializeField] private float audioOffset = 0f;

        [SerializeField] private bool playOnStart = true;

        [Tooltip("Log clip lengths at start and drift once a second. Turn off once sync is settled.")]
        [SerializeField] private bool diagnose = true;

        [Tooltip("Wait for frame times to settle before starting. Prevents the animator losing " +
                 "time to a loading hitch while audio keeps running in real time.")]
        [SerializeField] private bool waitForWarmFrames = true;

        [Tooltip("Seconds after start to apply ONE audio correction. 0 disables. " +
                 "Deliberately one-shot: correcting every frame makes the mouth stutter.")]
        [SerializeField] private float resyncAfter = 0.75f;

        private void Reset()
        {
            animator = GetComponentInChildren<Animator>();
            audioSource = GetComponent<AudioSource>();
            if (audioSource != null)
            {
                audioSource.playOnAwake = false;
                audioSource.spatialBlend = 0f;
            }
        }

        private void Awake()
        {
            if (animator == null) animator = GetComponentInChildren<Animator>();
            if (audioSource == null) audioSource = GetComponent<AudioSource>();
            if (audioSource != null) audioSource.playOnAwake = false;
        }

        private void Start()
        {
            if (!playOnStart) return;
            if (waitForWarmFrames) StartCoroutine(PlayWhenWarm());
            else Play();
        }

        /// <summary>
        /// Holds off until several consecutive frames render quickly.
        ///
        /// AudioSource runs on the DSP clock and advances in real time regardless
        /// of frame rate, while the Animator advances by Time.deltaTime, which
        /// Unity CLAMPS to Time.maximumDeltaTime (0.333s). A loading hitch
        /// therefore costs the animator time that the audio keeps - measured as a
        /// constant +1.43s of audio lead on this scene, which no amount of
        /// clip-length matching would have fixed.
        /// </summary>
        private IEnumerator PlayWhenWarm()
        {
            const int needed = 3;
            int calm = 0;
            float waited = 0f;
            while (calm < needed && waited < 5f)
            {
                yield return null;
                waited += Time.unscaledDeltaTime;
                calm = Time.unscaledDeltaTime < 0.05f ? calm + 1 : 0;
            }
            if (diagnose)
                Debug.Log($"[TripoFaceRig] frames settled after {waited:0.00}s; starting.", this);
            Play();
        }

        [ContextMenu("Play")]
        public void Play()
        {
            if (animator == null)
            {
                Debug.LogWarning("[TripoFaceRig] FacePerformancePlayer has no Animator.", this);
                return;
            }

            // Rebind resets EVERY layer to its default state at t=0. Playing
            // layer 0 alone is wrong once a layered controller exists: layer 0 is
            // the body, so the face layer kept running from scene load and was
            // already partway through when the audio started - which reads as the
            // audio racing ahead of the face.
            if (string.IsNullOrEmpty(stateName))
            {
                animator.Rebind();
            }
            else
            {
                animator.Rebind();
                animator.Play(stateName, faceLayer, 0f);
            }
            animator.Update(0f);

            if (audioSource == null || audioSource.clip == null)
            {
                Debug.LogWarning("[TripoFaceRig] No dialogue clip assigned; playing face only.", this);
                return;
            }

            audioSource.Stop();
            audioSource.time = 0f;
            if (audioOffset > 0f) audioSource.PlayDelayed(audioOffset);
            else audioSource.Play();

            CancelInvoke(nameof(ResyncOnce));
            if (resyncAfter > 0f) Invoke(nameof(ResyncOnce), resyncAfter);
            if (diagnose) LogSetup();
        }

        /// <summary>One correction, never continuous - per-frame nudging stutters the mouth.</summary>
        private void ResyncOnce()
        {
            if (animator == null || audioSource == null || !audioSource.isPlaying) return;
            var st = animator.GetCurrentAnimatorStateInfo(faceLayer);
            float animTime = st.normalizedTime * st.length;
            float drift = audioSource.time - animTime;
            if (Mathf.Abs(drift) < 0.05f) return;
            float target = Mathf.Clamp(animTime, 0f, audioSource.clip.length - 0.05f);
            audioSource.time = target;
            if (diagnose)
                Debug.Log($"[TripoFaceRig] one-shot resync: drift was {drift:+0.00;-0.00}s, " +
                          $"audio moved to {target:0.00}s.", this);
        }

        /// <summary>
        /// Prints the numbers that decide whether audio and face can line up at
        /// all. Guessing at sync without these wasted two rounds already.
        /// </summary>
        private void LogSetup()
        {
            var st = animator.GetCurrentAnimatorStateInfo(faceLayer);
            Debug.Log(
                $"[TripoFaceRig] layer {faceLayer} state length {st.length:0.000}s, " +
                $"speed {st.speed:0.###}, loop {st.loop}, layers {animator.layerCount}, " +
                $"animator.speed {animator.speed:0.###}, updateMode {animator.updateMode}", this);
            Debug.Log(
                $"[TripoFaceRig] audio '{audioSource.clip.name}' {audioSource.clip.length:0.000}s " +
                $"@{audioSource.clip.frequency}Hz, pitch {audioSource.pitch:0.###}", this);

            float ratio = st.length > 0f ? audioSource.clip.length / st.length : 0f;
            if (Mathf.Abs(ratio - 1f) > 0.05f)
            {
                Debug.LogWarning(
                    $"[TripoFaceRig] audio/animation length ratio {ratio:0.000}. They cannot stay " +
                    "in sync. Ratio near 2.0 or 0.5 means an fps mismatch between the Blender " +
                    "scene and the FBX import; anything else means the wrong clip is on this layer.",
                    this);
            }
            CancelInvoke(nameof(ReportDrift));
            InvokeRepeating(nameof(ReportDrift), 1f, 1f);
        }

        private void ReportDrift()
        {
            if (audioSource == null || !audioSource.isPlaying)
            {
                CancelInvoke(nameof(ReportDrift));
                return;
            }
            var st = animator.GetCurrentAnimatorStateInfo(faceLayer);
            float animTime = st.normalizedTime * st.length;
            Debug.Log($"[TripoFaceRig] t={audioSource.time:0.00}s  face={animTime:0.00}s  " +
                      $"drift={audioSource.time - animTime:+0.00;-0.00}s " +
                      $"(normalizedTime {st.normalizedTime:0.00})", this);
        }

        [ContextMenu("Stop")]
        public void Stop()
        {
            if (audioSource != null) audioSource.Stop();
        }

        /// <summary>Seconds the audio leads (+) or lags (-) the animation. For diagnosis.</summary>
        public float MeasureDrift()
        {
            if (animator == null || audioSource == null || !audioSource.isPlaying) return 0f;
            var st = animator.GetCurrentAnimatorStateInfo(faceLayer);
            float animTime = st.normalizedTime * st.length;
            return audioSource.time - animTime;
        }
    }
}
