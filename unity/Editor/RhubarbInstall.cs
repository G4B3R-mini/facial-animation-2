// Installs Rhubarb into StreamingAssets so lipsync survives a build.
//
//   Tools > Tripo Face Rig > 11. Install Rhubarb Into StreamingAssets
//
// Anything outside StreamingAssets is gone in a player build, so the editor
// fallback path in RuntimeLipSyncService works only while you are in the editor.
// Copies rhubarb.exe plus, for PocketSphinx, res/sphinx. Skips extras/ (19MB of
// After Effects and Spine integrations) and tests/ (53MB), which the runtime
// never touches.
using System;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace TripoFaceRig.EditorTools
{
    public static class HelenRhubarbInstall
    {
        private const string DestRel = "Assets/StreamingAssets/Rhubarb";
        private const string SourcePreference = "TripoFaceRig.RhubarbSource";

        [MenuItem("Tools/Tripo Face Rig/11. Install Rhubarb Into StreamingAssets")]
        public static void Install()
        {
            string source = EditorPrefs.GetString(SourcePreference, "");
            if (!File.Exists(Path.Combine(source, ExecutableName())))
            {
                source = EditorUtility.OpenFolderPanel(
                    "Choose the extracted Rhubarb distribution", source, "");
                if (string.IsNullOrEmpty(source)) return;
                EditorPrefs.SetString(SourcePreference, source);
            }
            if (!File.Exists(Path.Combine(source, ExecutableName())))
            {
                Debug.LogError($"[TripoFaceRig] No {ExecutableName()} under {source}.");
                return;
            }

            bool withSphinx = EditorUtility.DisplayDialog(
                "Install Rhubarb",
                "Include the PocketSphinx data (res/sphinx, ~83MB)?\n\n" +
                "With it: accurate English recognition that can use the dialogue text " +
                "for grammar-constrained alignment. This is the recommended option.\n\n" +
                "Without it: only the 'phonetic' recognizer works - about 3x faster and " +
                "2.6MB total, language-independent, but noticeably less accurate.",
                "Include it (recommended)", "Exe only");

            Directory.CreateDirectory(DestRel);
            File.Copy(Path.Combine(source, ExecutableName()),
                      Path.Combine(DestRel, ExecutableName()), true);

            long bytes = new FileInfo(Path.Combine(DestRel, ExecutableName())).Length;

            if (withSphinx)
            {
                string src = Path.Combine(source, "res");
                string dst = Path.Combine(DestRel, "res");
                if (Directory.Exists(src))
                {
                    bytes += CopyTree(src, dst);
                }
                else
                {
                    Debug.LogWarning($"[TripoFaceRig] {src} is missing; PocketSphinx will not run. " +
                                     "Set the recognizer to Phonetic.");
                }
            }
            else
            {
                // Stale sphinx data would silently keep working and hide the fact
                // that the build no longer ships it.
                string dst = Path.Combine(DestRel, "res");
                if (Directory.Exists(dst)) Directory.Delete(dst, true);
            }

            AssetDatabase.Refresh();
            Debug.Log($"[TripoFaceRig] Installed Rhubarb to {DestRel} " +
                      $"({bytes / 1024f / 1024f:0.0}MB, " +
                      $"{(withSphinx ? "PocketSphinx + phonetic" : "phonetic only")}). " +
                      "Set RuntimeLipSyncService.recognizer to match.");
        }

        private static string ExecutableName()
        {
            return Application.platform == RuntimePlatform.WindowsEditor ? "rhubarb.exe" : "rhubarb";
        }

        private static long CopyTree(string src, string dst)
        {
            Directory.CreateDirectory(dst);
            long total = 0;
            foreach (var f in Directory.GetFiles(src))
            {
                string to = Path.Combine(dst, Path.GetFileName(f));
                File.Copy(f, to, true);
                total += new FileInfo(to).Length;
            }
            foreach (var d in Directory.GetDirectories(src))
                total += CopyTree(d, Path.Combine(dst, Path.GetFileName(d)));
            return total;
        }
    }
}
