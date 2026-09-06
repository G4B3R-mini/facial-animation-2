using System;
using System.Collections;
using System.Diagnostics;
using System.IO;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;
using Debug = UnityEngine.Debug;

namespace TripoFaceRig
{
    /// <summary>
    /// Turns a freshly generated TTS line into accurate lipsync at runtime.
    ///
    /// The premise that makes this work: a local TTS server hands back a finished
    /// FILE, not a live microphone stream, and the LLM that wrote the line hands
    /// back its text. So we can run real recognition BEFORE playback rather than
    /// guessing at the waveform during it - which is why this matches the words
    /// and MFCC classification does not.
    ///
    /// Measured on an 18.44s clip: pocketSphinx 3.84s (0.21x realtime), phonetic
    /// 1.27s (0.07x). A typical 4s line therefore costs roughly 0.85s or 0.28s
    /// before she starts speaking. Rhubarb runs on a worker thread, so that cost
    /// is latency, never a frame hitch.
    ///
    /// Deliberately knows nothing about your LLM or TTS package. Feed it bytes
    /// and text; it calls back when the line is playing.
    /// </summary>
    public sealed class RuntimeLipSyncService : MonoBehaviour
    {
        public enum Recognizer
        {
            /// <summary>Accurate, English, and uses the dialog text. Needs res/sphinx (~83MB).</summary>
            PocketSphinx,
            /// <summary>Language-independent and ~3x faster, but less accurate. Needs no data files.</summary>
            Phonetic,
        }

        [SerializeField] private RhubarbVisemePlayer player;
        [SerializeField] private Recognizer recognizer = Recognizer.PocketSphinx;

        [Tooltip("Folder under StreamingAssets holding rhubarb.exe (and res/ for PocketSphinx).")]
        [SerializeField] private string streamingSubfolder = "Rhubarb";

        [Tooltip("Editor-only fallback, so you can test before installing into StreamingAssets.")]
        [SerializeField] private string editorFallbackExe = "";

        [Tooltip("Give up on a line if analysis takes longer than this.")]
        [SerializeField] private float timeoutSeconds = 20f;

        [SerializeField] private bool diagnose = true;

        /// <summary>Raised when a line begins playing. Use it to start gestures.</summary>
        public event Action<AudioClip> OnLineStarted;

        private void Awake()
        {
            if (player == null) player = GetComponent<RhubarbVisemePlayer>();
        }

        /// <summary>
        /// Speak a line. <paramref name="wavBytes"/> is what the TTS server
        /// returned (RIFF/WAV); <paramref name="text"/> is what the LLM wrote.
        ///
        /// Pass the text when you have it. Rhubarb's docs recommend it and it
        /// demonstrably reaches the recognizer - a deliberately WRONG transcript
        /// changed 1 of 91 cues on the reference clip - but the gain from a
        /// CORRECT transcript has not been measured here, so treat it as a cheap
        /// improvement rather than a decisive one. Since the LLM always knows the
        /// line, it costs nothing to pass.
        /// </summary>
        public void Speak(byte[] wavBytes, string text)
        {
            if (wavBytes == null || wavBytes.Length == 0)
            {
                Debug.LogError("[TripoFaceRig] Speak called with no audio.", this);
                return;
            }
            StartCoroutine(SpeakRoutine(wavBytes, text));
        }

        private IEnumerator SpeakRoutine(byte[] wavBytes, string text)
        {
            // Rhubarb reads from disk, so the clip has to land somewhere real.
            // Temporary cache, uniquely named: lines can overlap.
            string stem = Path.Combine(Application.temporaryCachePath,
                                       "tts_" + DateTime.UtcNow.Ticks);
            string wavPath = stem + ".wav";
            string txtPath = stem + ".txt";

            Exception writeError = null;
            var write = Task.Run(() =>
            {
                try
                {
                    File.WriteAllBytes(wavPath, wavBytes);
                    if (!string.IsNullOrWhiteSpace(text)) File.WriteAllText(txtPath, text);
                }
                catch (Exception e) { writeError = e; }
            });
            while (!write.IsCompleted) yield return null;
            if (writeError != null)
            {
                Debug.LogError($"[TripoFaceRig] Could not stage the TTS clip: {writeError.Message}", this);
                yield break;
            }

            string exe = ResolveExe();
            if (exe == null) { Cleanup(wavPath, txtPath); yield break; }

            // ---- analysis, on a worker thread so the frame rate is untouched
            string json = null;
            string error = null;
            var sw = Stopwatch.StartNew();
            bool hasText = !string.IsNullOrWhiteSpace(text);
            var job = Task.Run(() =>
            {
                try { json = RunRhubarb(exe, wavPath, hasText ? txtPath : null, recognizer, out error); }
                catch (Exception e) { error = e.Message; }
            });

            float waited = 0f;
            while (!job.IsCompleted && waited < timeoutSeconds)
            {
                waited += Time.unscaledDeltaTime;
                yield return null;
            }
            sw.Stop();

            if (!job.IsCompleted)
            {
                Debug.LogError($"[TripoFaceRig] Rhubarb timed out after {timeoutSeconds}s.", this);
                Cleanup(wavPath, txtPath);
                yield break;
            }
            if (json == null)
            {
                Debug.LogError($"[TripoFaceRig] Rhubarb failed: {error}", this);
                Cleanup(wavPath, txtPath);
                yield break;
            }

            // ---- decode the wav into a clip (main thread; Unity API)
            AudioClip clip = null;
            using (var req = UnityWebRequestMultimedia.GetAudioClip("file://" + wavPath, AudioType.WAV))
            {
                yield return req.SendWebRequest();
                if (req.result != UnityWebRequest.Result.Success)
                {
                    Debug.LogError($"[TripoFaceRig] Could not decode the TTS wav: {req.error}", this);
                    Cleanup(wavPath, txtPath);
                    yield break;
                }
                clip = DownloadHandlerAudioClip.GetContent(req);
            }

            if (player == null)
            {
                Debug.LogError("[TripoFaceRig] No RhubarbVisemePlayer assigned.", this);
                Cleanup(wavPath, txtPath);
                yield break;
            }

            player.enabled = true;
            player.Play(clip, json);
            OnLineStarted?.Invoke(clip);

            if (diagnose)
                Debug.Log($"[TripoFaceRig] Line ready in {sw.ElapsedMilliseconds}ms " +
                          $"({recognizer}{(hasText ? " + dialog text" : ", no text")}) " +
                          $"for {clip.length:0.00}s of audio " +
                          $"= {sw.ElapsedMilliseconds / 1000f / Mathf.Max(clip.length, 0.01f):0.00}x realtime.", this);

            // Keep the wav until playback ends: the AudioClip streams from it.
            yield return new WaitForSeconds(clip.length + 0.5f);
            Cleanup(wavPath, txtPath);
        }

        private string ResolveExe()
        {
            string executable = Application.platform == RuntimePlatform.WindowsPlayer ||
                                Application.platform == RuntimePlatform.WindowsEditor ? "rhubarb.exe" : "rhubarb";
            string streaming = Path.Combine(Application.streamingAssetsPath,
                                            streamingSubfolder, executable);
            if (File.Exists(streaming)) return streaming;

#if UNITY_EDITOR
            if (File.Exists(editorFallbackExe))
            {
                if (diagnose)
                    Debug.LogWarning("[TripoFaceRig] Using the configured editor fallback. Copy the full " +
                                     "platform-specific Rhubarb distribution into StreamingAssets/" +
                                     streamingSubfolder + " before building runtime recognition.", this);
                return editorFallbackExe;
            }
#endif
            Debug.LogError($"[TripoFaceRig] Rhubarb not found at {streaming}. Download the full OS archive from " +
                           "https://github.com/DanielSWolf/rhubarb-lip-sync/releases and extract it there " +
                           "with recognizer resources, or set editorFallbackExe for editor testing.", this);
            return null;
        }

        private static string RunRhubarb(string exe, string wavPath, string dialogPath,
                                         Recognizer recognizer, out string error)
        {
            error = null;
            string outPath = wavPath + ".json";
            string rec = recognizer == Recognizer.Phonetic ? "phonetic" : "pocketSphinx";
            string args = $"-q -r {rec} -f json -o \"{outPath}\" ";
            if (dialogPath != null) args += $"-d \"{dialogPath}\" ";
            args += $"\"{wavPath}\"";

            var psi = new ProcessStartInfo(exe, args)
            {
                UseShellExecute = false,
                RedirectStandardError = true,
                CreateNoWindow = true,
                // pocketSphinx resolves res/sphinx relative to the executable.
                WorkingDirectory = Path.GetDirectoryName(exe),
            };

            using (var p = Process.Start(psi))
            {
                string err = p.StandardError.ReadToEnd();
                p.WaitForExit();
                if (p.ExitCode != 0)
                {
                    error = $"exit {p.ExitCode}: {err}";
                    return null;
                }
            }

            if (!File.Exists(outPath)) { error = "rhubarb produced no output file"; return null; }
            string json = File.ReadAllText(outPath);
            try { File.Delete(outPath); } catch { }
            return json;
        }

        private static void Cleanup(params string[] paths)
        {
            foreach (var p in paths)
                try { if (p != null && File.Exists(p)) File.Delete(p); } catch { }
        }
    }
}
