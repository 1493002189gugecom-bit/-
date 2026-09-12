using System.Collections.Generic;
using UnityEngine;

namespace SmartHome
{
    /// <summary>
    /// Applies authoritative state to the scene.
    ///
    /// Positions come only from the state service; camera detections never move
    /// these objects. Broadcast playback is driven by the queue head so only one
    /// room can ever be "playing".
    /// </summary>
    public sealed class SceneStateApplier : MonoBehaviour
    {
        [Tooltip("Client that feeds state into this applier.")]
        public HomeServiceClient client;

        [Tooltip("Highlight colour for the room currently being announced.")]
        public Color broadcastingColor = new Color(1f, 0.85f, 0.3f, 1f);

        public Color idleColor = new Color(0.35f, 0.55f, 0.75f, 1f);

        private readonly Dictionary<string, Transform> _deviceViews = new Dictionary<string, Transform>();
        private readonly Dictionary<string, Transform> _personViews = new Dictionary<string, Transform>();
        private readonly Dictionary<string, Renderer> _roomRenderers = new Dictionary<string, Renderer>();
        private readonly Dictionary<string, TextMesh> _deviceLabels = new Dictionary<string, TextMesh>();

        private HomeSnapshot _snapshot;

        private void OnEnable()
        {
            if (client != null)
            {
                client.SnapshotReceived += Apply;
                client.StatusChanged += OnStatus;
                client.ErrorOccurred += OnError;
            }
        }

        private void OnDisable()
        {
            if (client != null)
            {
                client.SnapshotReceived -= Apply;
                client.StatusChanged -= OnStatus;
                client.ErrorOccurred -= OnError;
            }
        }

        public void Apply(HomeSnapshot snapshot)
        {
            _snapshot = snapshot;

            foreach (var room in snapshot.rooms.Values)
            {
                EnsureRoomView(room);
            }

            foreach (var device in snapshot.devices.Values)
            {
                ApplyDevice(device);
            }

            foreach (var person in snapshot.persons.Values)
            {
                ApplyPerson(person);
            }

            ApplyBroadcastHighlight(snapshot);
        }

        private void EnsureRoomView(RoomDto room)
        {
            if (_roomRenderers.ContainsKey(room.id))
            {
                return;
            }

            var go = GameObject.CreatePrimitive(PrimitiveType.Cube);
            go.name = "room-" + room.id;
            go.transform.SetParent(transform, false);
            _roomRenderers[room.id] = go.GetComponent<Renderer>();

            var labelGo = new GameObject("label");
            labelGo.transform.SetParent(go.transform, false);
            labelGo.transform.localPosition = new Vector3(0f, 0.6f, 0f);
            var label = labelGo.AddComponent<TextMesh>();
            label.text = room.name;
            label.characterSize = 0.1f;
            label.anchor = TextAnchor.MiddleCenter;
        }

        private void ApplyDevice(DeviceDto device)
        {
            Transform view;
            if (!_deviceViews.TryGetValue(device.id, out view))
            {
                var go = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                go.name = "device-" + device.id;
                go.transform.SetParent(transform, false);
                go.transform.localScale = Vector3.one * 0.25f;
                view = go.transform;
                _deviceViews[device.id] = view;

                var labelGo = new GameObject("label");
                labelGo.transform.SetParent(view, false);
                labelGo.transform.localPosition = new Vector3(0f, 0.8f, 0f);
                var label = labelGo.AddComponent<TextMesh>();
                label.characterSize = 0.08f;
                label.anchor = TextAnchor.MiddleCenter;
                _deviceLabels[device.id] = label;
            }

            var renderer = view.GetComponent<Renderer>();
            if (renderer != null)
            {
                if (!device.online)
                {
                    // Offline is visibly different: state must never look live.
                    renderer.material.color = Color.gray;
                }
                else
                {
                    renderer.material.color = device.on
                        ? Color.Lerp(Color.black, Color.white, device.brightness / 100f)
                        : Color.black;
                }
            }

            TextMesh text;
            if (_deviceLabels.TryGetValue(device.id, out text))
            {
                text.text = device.online
                    ? device.name + DescribeState(device)
                    : device.name + "（离线）";
            }
        }

        private static string DescribeState(DeviceDto device)
        {
            if (!device.on)
            {
                return " 关";
            }

            if (device.type == "light")
            {
                return " 开 " + device.brightness + "%";
            }

            if (device.type == "ac")
            {
                return " 开 " + device.mode + " " + device.target_temp.ToString("0.#") + "°";
            }

            return " 开";
        }

        private void ApplyPerson(PersonDto person)
        {
            Transform view;
            if (!_personViews.TryGetValue(person.id, out view))
            {
                var go = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
                go.name = "person-" + person.id;
                go.transform.SetParent(transform, false);
                go.transform.localScale = new Vector3(0.2f, 0.4f, 0.2f);
                view = go.transform;
                _personViews[person.id] = view;

                var labelGo = new GameObject("label");
                labelGo.transform.SetParent(view, false);
                labelGo.transform.localPosition = new Vector3(0f, 1.2f, 0f);
                var label = labelGo.AddComponent<TextMesh>();
                label.text = person.display_name;
                label.characterSize = 0.08f;
                label.anchor = TextAnchor.MiddleCenter;
            }

            var renderer = view.GetComponent<Renderer>();
            if (renderer != null)
            {
                // Unknown location must look unknown rather than staying put.
                renderer.material.color = person.location_known ? Color.green : Color.red;
            }

            if (person.location_known && !string.IsNullOrEmpty(person.room_id))
            {
                Renderer room;
                if (_roomRenderers.TryGetValue(person.room_id, out room))
                {
                    // PersonDto.x/y are plain floats (0 when the service sends
                    // null), so no nullable accessor is needed.
                    view.position = room.transform.position + new Vector3(person.x, 0.4f, person.y);
                }
            }
        }

        private void ApplyBroadcastHighlight(HomeSnapshot snapshot)
        {
            BroadcastDto head = snapshot.HeadBroadcast;
            foreach (var pair in _roomRenderers)
            {
                Renderer renderer = pair.Value;
                bool isHead = head != null && head.room_id == pair.Key;
                renderer.material.color = isHead ? broadcastingColor : idleColor;
            }
        }

        private void OnStatus(string status)
        {
            Debug.Log("[home-service] " + status);
        }

        private void OnError(string error)
        {
            Debug.LogWarning("[home-service] " + error);
        }
    }
}
