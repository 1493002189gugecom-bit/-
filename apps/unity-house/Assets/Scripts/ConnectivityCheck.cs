using System.Collections;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

namespace SmartHome
{
    /// <summary>
    /// Phase C step 1: prove the chosen Unity version can (a) parse the home
    /// service JSON, (b) reach the loopback service, and (c) use WebSocket.
    ///
    /// Results are printed to the Console and shown on screen so a screenshot is
    /// enough evidence. Attach to any GameObject in an otherwise empty scene.
    /// </summary>
    public sealed class ConnectivityCheck : MonoBehaviour
    {
        [Tooltip("Loopback address of the home-service.")]
        public string baseUrl = "http://127.0.0.1:8765";

        private readonly StringBuilder _report = new StringBuilder();

        private void Start()
        {
            _report.AppendLine("Unity " + Application.unityVersion);
            _report.AppendLine("API compatibility: " + ApiCompatibilityLabel());
            _report.AppendLine("Platform: " + Application.platform);
            _report.AppendLine();
            StartCoroutine(RunChecks());
        }

        private IEnumerator RunChecks()
        {
            yield return CheckServiceReachable();
            yield return CheckStateParses();
            CheckWebSocketAvailability();

            Debug.Log("[ConnectivityCheck]\n" + _report);
        }

        private IEnumerator CheckServiceReachable()
        {
            using (UnityWebRequest request = UnityWebRequest.Get(baseUrl + "/health"))
            {
                request.timeout = 5;
                yield return request.SendWebRequest();
                if (IsFailure(request))
                {
                    _report.AppendLine("[FAIL] /health unreachable: " + request.error);
                    _report.AppendLine("       Start it with: .venv\\Scripts\\python.exe apps/home-service/src/server.py");
                    yield break;
                }

                _report.AppendLine("[OK]   /health reachable");
                _report.AppendLine("       " + Shorten(request.downloadHandler.text));
            }
        }

        private IEnumerator CheckStateParses()
        {
            using (UnityWebRequest request = UnityWebRequest.Get(baseUrl + "/snapshot"))
            {
                request.timeout = 5;
                yield return request.SendWebRequest();
                if (IsFailure(request))
                {
                    _report.AppendLine("[FAIL] /snapshot unreachable: " + request.error);
                    yield break;
                }

                string json = request.downloadHandler.text;
                HomeSnapshot snapshot = null;
                try
                {
                    snapshot = StateParser.ParseSync(json);
                }
                catch (System.Exception ex)
                {
                    _report.AppendLine("[FAIL] JSON parse threw: " + ex.Message);
                    yield break;
                }

                if (snapshot == null)
                {
                    _report.AppendLine("[FAIL] JSON parse returned null");
                    yield break;
                }

                bool complete = snapshot.rooms.Count > 0 && snapshot.devices.Count > 0 && snapshot.persons.Count > 0;
                _report.AppendLine(complete ? "[OK]   JSON parsed" : "[FAIL] JSON parsed but empty");
                _report.AppendLine("       version=" + snapshot.version +
                                   " rooms=" + snapshot.rooms.Count +
                                   " devices=" + snapshot.devices.Count +
                                   " persons=" + snapshot.persons.Count +
                                   " broadcasts=" + snapshot.broadcasts.Count);
                foreach (var pair in snapshot.rooms)
                {
                    _report.AppendLine("       room " + pair.Value.id + " (" + pair.Value.name + ")" +
                                       " temp=" + pair.Value.simulated_temp);
                }

                foreach (var pair in snapshot.persons)
                {
                    _report.AppendLine("       person " + pair.Value.display_name +
                                       " room=" + (pair.Value.room_id ?? "<unknown>") +
                                       " known=" + pair.Value.location_known);
                }
            }
        }

        private void CheckWebSocketAvailability()
        {
            // Unity 2022.3 has no separate websocket module: WebSocket support
            // ships inside com.unity.modules.unitywebrequest. Probe the two
            // mechanisms that can actually exist, and report honestly rather
            // than asserting a capability that may be absent.
            var probes = new[]
            {
                "UnityEngine.Networking.WebSocket, UnityEngine.UnityWebRequestModule",
                "System.Net.WebSockets.ClientWebSocket, System.Net.WebSockets.Client",
                "System.Net.WebSockets.ClientWebSocket, netstandard",
            };

            foreach (string probe in probes)
            {
                System.Type found = System.Type.GetType(probe);
                if (found != null)
                {
                    _report.AppendLine("[OK]   WebSocket available: " + found.FullName);
                    return;
                }
            }

            _report.AppendLine("[WARN] No WebSocket type resolved in this profile.");
            _report.AppendLine("       Phase C uses HTTP polling only, so this does not block step 1.");
        }

        private static string ApiCompatibilityLabel()
        {
#if NET_STANDARD_2_1
            return ".NET Standard 2.1";
#elif NET_4_6
            return ".NET 4.x";
#else
            return "unknown";
#endif
        }

#if UNITY_2020_1_OR_NEWER
        private static bool IsFailure(UnityWebRequest request)
        {
            return request.result != UnityWebRequest.Result.Success;
        }
#else
        private static bool IsFailure(UnityWebRequest request)
        {
            return request.isNetworkError || request.isHttpError;
        }
#endif

        private static string Shorten(string text)
        {
            if (string.IsNullOrEmpty(text))
            {
                return "(empty)";
            }

            return text.Length <= 160 ? text : text.Substring(0, 160) + "...";
        }

        private void OnGUI()
        {
            GUI.Label(new Rect(10, 10, 900, 560), _report.ToString());
        }
    }
}
