using System;
using System.Diagnostics;
using System.IO;
using System.Threading.Tasks;
using UnityEditor;
using UnityEngine;

namespace TripoFaceRig.EditorTools
{
    public static class CharacterRhubarb
    {
        [Serializable] private class Cue { public float start; public float end; public string value; }
        [Serializable] private class CueFile { public Cue[] mouthCues; }

        public static void Validate(string json, float duration)
        {
            var file = JsonUtility.FromJson<CueFile>(json);
            if (file?.mouthCues == null || file.mouthCues.Length == 0) throw new ArgumentException("Rhubarb JSON has no mouth cues.");
            float previous = 0;
            foreach (var cue in file.mouthCues)
            {
                if (cue == null || !float.IsFinite(cue.start) || !float.IsFinite(cue.end) || cue.start < previous - 0.001f ||
                    cue.end <= cue.start || cue.end > duration + 0.25f || string.IsNullOrEmpty(cue.value) ||
                    cue.value.Length != 1 || !"ABCDEFGHX".Contains(cue.value))
                    throw new ArgumentException("Cue times or values are invalid for this voice. Generate a matching JSON file.");
                previous = cue.end;
            }
        }

        public static async Task<TextAsset> Generate(AudioClip voice, string executable)
        {
            string audioPath = Path.GetFullPath(AssetDatabase.GetAssetPath(voice));
            if (!File.Exists(audioPath) || !audioPath.EndsWith(".wav", StringComparison.OrdinalIgnoreCase))
                throw new ArgumentException("Automatic timing generation requires an imported WAV. Convert the audio to WAV or supply matching Rhubarb JSON.");
            if (string.IsNullOrWhiteSpace(executable)) executable = Environment.GetEnvironmentVariable("RHUBARB_PATH");
            if (string.IsNullOrWhiteSpace(executable))
            {
                string name = Application.platform == RuntimePlatform.WindowsEditor ? "rhubarb.exe" : "rhubarb";
                foreach (var folder in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator))
                {
                    string candidate = Path.Combine(folder.Trim('"'), name);
                    if (File.Exists(candidate)) { executable = candidate; break; }
                }
            }
            if (string.IsNullOrWhiteSpace(executable) || !File.Exists(executable))
                throw new ArgumentException("Rhubarb missing. Click Download Rhubarb, extract the entire OS archive, then Browse for its executable; or supply existing JSON.");
            executable = Path.GetFullPath(executable);
            string output = Path.Combine(Path.GetTempPath(), "tripo_cues_" + Guid.NewGuid().ToString("N") + ".json");
            string json;
            try
            {
                string tool = executable;
                json = await Task.Run(() => {
                    var info = new ProcessStartInfo(tool) {
                        Arguments = "-r pocketSphinx -f json -o " + Quote(output) + " " + Quote(audioPath),
                        WorkingDirectory = Path.GetDirectoryName(tool), UseShellExecute = false,
                        CreateNoWindow = true, RedirectStandardError = true, RedirectStandardOutput = true
                    };
                    using (var process = Process.Start(info))
                    {
                        if (process == null) throw new IOException("Could not start Rhubarb.");
                        var error = process.StandardError.ReadToEndAsync();
                        var stdout = process.StandardOutput.ReadToEndAsync();
                        if (!process.WaitForExit(120000)) { process.Kill(); throw new TimeoutException("Rhubarb exceeded two minutes. Generate cues separately for long recordings."); }
                        Task.WaitAll(error, stdout);
                        if (process.ExitCode != 0) throw new IOException("Rhubarb failed: " + error.Result + "\nKeep the complete distribution including res/sphinx beside the executable.");
                    }
                    return File.ReadAllText(output);
                });
            }
            finally { if (File.Exists(output)) File.Delete(output); }
            Validate(json, voice.length);
            string root = "Assets/TripoFaceRigGenerated";
            if (!AssetDatabase.IsValidFolder(root)) AssetDatabase.CreateFolder("Assets", "TripoFaceRigGenerated");
            string asset = AssetDatabase.GenerateUniqueAssetPath(root + "/VoiceCues.json");
            File.WriteAllText(asset, json);
            AssetDatabase.ImportAsset(asset);
            return AssetDatabase.LoadAssetAtPath<TextAsset>(asset);
        }

        private static string Quote(string value)
        {
            if (value.Contains("\"")) throw new ArgumentException("A file path contains an unsupported quote.");
            return "\"" + value + "\"";
        }
    }
}
