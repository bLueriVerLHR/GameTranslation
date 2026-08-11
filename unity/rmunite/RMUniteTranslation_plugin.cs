using System;
using System.Collections.Generic;
using System.IO;
using BepInEx;
using HarmonyLib;
using Newtonsoft.Json;
using UnityEngine.UI;

namespace RMUniteTranslation
{
    [BepInPlugin("local.rmunite.translation", "RM Unite Translation", "1.0.0")]
    public class Plugin : BaseUnityPlugin
    {
        private static Dictionary<string, string> _map;
        private static int _hits;
        private static int _misses;
        private static string _missLog;

        private void Awake()
        {
            var path = Path.Combine(Paths.GameRootPath, "translated.json");
            _missLog = Path.Combine(Paths.GameRootPath, "translation_miss.log");
            _hits = 0;
            _misses = 0;
            if (!File.Exists(path))
            {
                Logger.LogError("translated.json not found at " + path);
                return;
            }
            try
            {
                var raw = JsonConvert.DeserializeObject<Dictionary<string, string>>(File.ReadAllText(path));
                _map = new Dictionary<string, string>(raw.Count, StringComparer.Ordinal);
                foreach (var kv in raw)
                    _map[kv.Key.Replace("\r", "")] = kv.Value;
            }
            catch (Exception e)
            {
                Logger.LogError("failed to parse translated.json: " + e);
                return;
            }
            Logger.LogInfo("loaded " + _map.Count + " translations");

            var harmony = new Harmony("local.rmunite.translation");
            try
            {
                harmony.PatchAll(typeof(Plugin).Assembly);
                Logger.LogInfo("harmony patches applied");
            }
            catch (Exception e)
            {
                Logger.LogError("patch failed: " + e);
            }

            var stats = new System.Threading.Timer(delegate
            {
                Logger.LogInfo(string.Format("[stats] hits={0} misses={1}", _hits, _misses));
            }, null, 15000, 15000);
        }

        private static string Translate(string value)
        {
            if (string.IsNullOrEmpty(value) || _map == null)
                return value;
            string zh;
            string norm = value.Replace("\r\n", "\n").Replace("\r", "\n");
            if (_map.TryGetValue(norm, out zh) && zh.Length > 0)
            {
                _hits++;
                // restore the original line-ending style: if the source ends
                // with CR, the translation must too, or the message window
                // breaks its line-break detection
                if (value.EndsWith("\r", StringComparison.Ordinal) && !zh.EndsWith("\r", StringComparison.Ordinal))
                    zh = zh + "\r";
                else if (value.EndsWith("\r\n", StringComparison.Ordinal) && !zh.EndsWith("\r\n", StringComparison.Ordinal))
                    zh = zh + "\r\n";
                return zh;
            }
            if (_misses++ < 30 && _missLog != null)
            {
                try { File.AppendAllText(_missLog, value.Replace("\r", "\\r").Replace("\n", "\\n") + "\n"); }
                catch { }
            }
            return value;
        }

        // main dialogue entry point: the whole message passes through here
        // on its way to the message window
        [HarmonyPatch(typeof(RPGMaker.Codebase.Runtime.Common.Component.HudHandler), "SetShowMessage")]
        internal static class PatchSetShowMessage
        {
            internal static void Prefix(RPGMaker.Codebase.Runtime.Common.Component.HudHandler __instance, ref string message)
            {
                message = Translate(message);
            }
        }

        // UI.Text fallback (menu/window labels, non-dialogue text): pure
        // dictionary lookup, no logging (typewriter hot path)
        [HarmonyPatch(typeof(UnityEngine.UI.Text), "set_text")]
        internal static class PatchUiText
        {
            internal static void Prefix(UnityEngine.UI.Text __instance, ref string value)
            {
                if (string.IsNullOrEmpty(value) || _map == null)
                    return;
                string zh;
                if (_map.TryGetValue(value.Replace("\r\n", "\n").Replace("\r", "\n"), out zh) && zh.Length > 0)
                    value = zh;
            }
        }

        // TMP fallback: must patch the base class TMP_Text (TextMeshProUGUI
        // does not implement this method; verified on Unity games)
        [HarmonyPatch(typeof(TMPro.TMP_Text), "set_text")]
        internal static class PatchTmp
        {
            internal static void Prefix(TMPro.TMP_Text __instance, ref string value)
            {
                if (string.IsNullOrEmpty(value) || _map == null)
                    return;
                string zh;
                if (_map.TryGetValue(value.Replace("\r\n", "\n").Replace("\r", "\n"), out zh) && zh.Length > 0)
                    value = zh;
            }
        }
    }
}
