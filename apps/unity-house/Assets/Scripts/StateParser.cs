using System;
using System.Collections.Generic;
using System.Text;
using UnityEngine;

namespace SmartHome
{
    [Serializable]
    public sealed class DeviceDto
    {
        public string id;
        public string room_id;
        public string room_name;
        public string type;
        public string name;
        public bool online;
        public bool on;
        public int brightness;
        public string mode;
        public float target_temp;
        public int version;
    }

    [Serializable]
    public sealed class PersonDto
    {
        public string id;
        public string display_name;
        public string room_id;
        public bool location_known;
        public float x;
        public float y;
        public int version;
    }

    [Serializable]
    public sealed class RoomDto
    {
        public string id;
        public string name;
        public float simulated_temp;
        public int version;
    }

    [Serializable]
    public sealed class BroadcastDto
    {
        public string id;
        public string room_id;
        public string room_name;
        public string text;
        public string state;
        public string receipt_id;
        public string error;
        public int version;
    }

    /// <summary>State applied to the scene by one sync response.</summary>
    public sealed class HomeSnapshot
    {
        public int version;
        public string mode = "snapshot";
        public readonly Dictionary<string, RoomDto> rooms = new Dictionary<string, RoomDto>();
        public readonly Dictionary<string, DeviceDto> devices = new Dictionary<string, DeviceDto>();
        public readonly Dictionary<string, PersonDto> persons = new Dictionary<string, PersonDto>();
        public readonly Dictionary<string, BroadcastDto> broadcasts = new Dictionary<string, BroadcastDto>();
        public readonly List<string> broadcastQueue = new List<string>();

        public BroadcastDto HeadBroadcast
        {
            get
            {
                for (int i = 0; i < broadcastQueue.Count; i++)
                {
                    BroadcastDto task;
                    if (broadcasts.TryGetValue(broadcastQueue[i], out task))
                    {
                        if (task.state != "played" && task.state != "failed" && task.state != "cancelled")
                        {
                            return task;
                        }
                    }
                }

                return null;
            }
        }
    }

    /// <summary>
    /// Minimal JSON handling without external packages.
    ///
    /// Unity's JsonUtility cannot deserialize top-level arrays, and the home
    /// service returns arrays of rooms/devices, so this parser walks the payload
    /// with a small hand-written scanner.
    /// </summary>
    public static class StateParser
    {
        public static HomeSnapshot ParseSync(string json)
        {
            var result = new HomeSnapshot();
            object root = MiniJson.Deserialize(json);
            var map = root as Dictionary<string, object>;
            if (map == null)
            {
                throw new FormatException("root is not a JSON object");
            }

            result.version = ReadInt(map, "version");
            result.mode = ReadString(map, "mode", "snapshot");

            foreach (var room in ReadArray(map, "rooms"))
            {
                RoomDto dto = ReadRoom(room as Dictionary<string, object>);
                if (dto != null)
                {
                    result.rooms[dto.id] = dto;
                }
            }

            foreach (var device in ReadArray(map, "devices"))
            {
                DeviceDto dto = ReadDevice(device as Dictionary<string, object>);
                if (dto != null)
                {
                    result.devices[dto.id] = dto;
                }
            }

            foreach (var person in ReadArray(map, "persons"))
            {
                PersonDto dto = ReadPerson(person as Dictionary<string, object>);
                if (dto != null)
                {
                    result.persons[dto.id] = dto;
                }
            }

            foreach (var task in ReadArray(map, "broadcasts"))
            {
                BroadcastDto dto = ReadBroadcast(task as Dictionary<string, object>);
                if (dto != null)
                {
                    result.broadcasts[dto.id] = dto;
                }
            }

            foreach (var id in ReadArray(map, "broadcast_queue"))
            {
                if (id != null)
                {
                    result.broadcastQueue.Add(id.ToString());
                }
            }

            return result;
        }

        public static string ExtractReceiptId(string json)
        {
            object root = MiniJson.Deserialize(json);
            var map = root as Dictionary<string, object>;
            if (map == null)
            {
                return null;
            }

            object task;
            if (map.TryGetValue("task", out task) && task is Dictionary<string, object> taskMap)
            {
                object receipt;
                if (taskMap.TryGetValue("receipt_id", out receipt) && receipt != null)
                {
                    return receipt.ToString();
                }
            }

            return null;
        }

        private static RoomDto ReadRoom(Dictionary<string, object> map)
        {
            if (map == null)
            {
                return null;
            }

            return new RoomDto
            {
                id = ReadString(map, "id", null),
                name = ReadString(map, "name", null),
                simulated_temp = ReadFloat(map, "simulated_temp"),
                version = ReadInt(map, "version"),
            };
        }

        private static DeviceDto ReadDevice(Dictionary<string, object> map)
        {
            if (map == null)
            {
                return null;
            }

            var dto = new DeviceDto
            {
                id = ReadString(map, "id", null),
                room_id = ReadString(map, "room_id", null),
                room_name = ReadString(map, "room_name", null),
                type = ReadString(map, "type", null),
                name = ReadString(map, "name", null),
                online = ReadBool(map, "online", true),
                version = ReadInt(map, "version"),
            };

            object state;
            if (map.TryGetValue("state", out state) && state is Dictionary<string, object> stateMap)
            {
                dto.on = ReadBool(stateMap, "on", false);
                dto.brightness = ReadInt(stateMap, "brightness");
                dto.mode = ReadString(stateMap, "mode", null);
                dto.target_temp = ReadFloat(stateMap, "target_temp");
            }

            return dto;
        }

        private static PersonDto ReadPerson(Dictionary<string, object> map)
        {
            if (map == null)
            {
                return null;
            }

            return new PersonDto
            {
                id = ReadString(map, "id", null),
                display_name = ReadString(map, "display_name", null),
                room_id = ReadString(map, "room_id", null),
                location_known = ReadBool(map, "location_known", false),
                x = ReadFloat(map, "x"),
                y = ReadFloat(map, "y"),
                version = ReadInt(map, "version"),
            };
        }

        private static BroadcastDto ReadBroadcast(Dictionary<string, object> map)
        {
            if (map == null)
            {
                return null;
            }

            return new BroadcastDto
            {
                id = ReadString(map, "id", null),
                room_id = ReadString(map, "room_id", null),
                room_name = ReadString(map, "room_name", null),
                text = ReadString(map, "text", null),
                state = ReadString(map, "state", null),
                receipt_id = ReadString(map, "receipt_id", null),
                error = ReadString(map, "error", null),
                version = ReadInt(map, "version"),
            };
        }

        private static IEnumerable<object> ReadArray(Dictionary<string, object> map, string key)
        {
            object value;
            if (map.TryGetValue(key, out value))
            {
                var list = value as List<object>;
                if (list != null)
                {
                    return list;
                }
            }

            return new List<object>();
        }

        private static string ReadString(Dictionary<string, object> map, string key, string fallback)
        {
            object value;
            if (map.TryGetValue(key, out value) && value != null)
            {
                return value.ToString();
            }

            return fallback;
        }

        private static int ReadInt(Dictionary<string, object> map, string key)
        {
            object value;
            if (map.TryGetValue(key, out value) && value != null)
            {
                double parsed;
                if (double.TryParse(value.ToString(), out parsed))
                {
                    return (int)parsed;
                }
            }

            return 0;
        }

        private static float ReadFloat(Dictionary<string, object> map, string key)
        {
            object value;
            if (map.TryGetValue(key, out value) && value != null)
            {
                float parsed;
                if (float.TryParse(value.ToString(), System.Globalization.NumberStyles.Float,
                        System.Globalization.CultureInfo.InvariantCulture, out parsed))
                {
                    return parsed;
                }
            }

            return 0f;
        }

        private static bool ReadBool(Dictionary<string, object> map, string key, bool fallback)
        {
            object value;
            if (map.TryGetValue(key, out value) && value != null)
            {
                if (value is bool)
                {
                    return (bool)value;
                }

                bool parsed;
                if (bool.TryParse(value.ToString(), out parsed))
                {
                    return parsed;
                }
            }

            return fallback;
        }
    }

    /// <summary>
    /// Small recursive-descent JSON reader.
    ///
    /// Kept deliberately tiny and dependency-free: the service emits plain JSON
    /// and the project must not depend on external packages.
    /// </summary>
    public static class MiniJson
    {
        public static object Deserialize(string json)
        {
            if (string.IsNullOrEmpty(json))
            {
                return null;
            }

            int index = 0;
            object value = ParseValue(json, ref index);
            SkipWhitespace(json, ref index);
            return value;
        }

        private static object ParseValue(string s, ref int i)
        {
            SkipWhitespace(s, ref i);
            if (i >= s.Length)
            {
                return null;
            }

            char c = s[i];
            switch (c)
            {
                case '{':
                    return ParseObject(s, ref i);
                case '[':
                    return ParseArray(s, ref i);
                case '"':
                    return ParseString(s, ref i);
                case 't':
                    i += 4;
                    return true;
                case 'f':
                    i += 5;
                    return false;
                case 'n':
                    i += 4;
                    return null;
                default:
                    return ParseNumber(s, ref i);
            }
        }

        private static Dictionary<string, object> ParseObject(string s, ref int i)
        {
            var result = new Dictionary<string, object>();
            i++; // {
            while (true)
            {
                SkipWhitespace(s, ref i);
                if (i >= s.Length)
                {
                    break;
                }

                if (s[i] == '}')
                {
                    i++;
                    break;
                }

                if (s[i] == ',')
                {
                    i++;
                    continue;
                }

                string key = ParseString(s, ref i);
                SkipWhitespace(s, ref i);
                if (i < s.Length && s[i] == ':')
                {
                    i++;
                }

                result[key] = ParseValue(s, ref i);
            }

            return result;
        }

        private static List<object> ParseArray(string s, ref int i)
        {
            var result = new List<object>();
            i++; // [
            while (true)
            {
                SkipWhitespace(s, ref i);
                if (i >= s.Length)
                {
                    break;
                }

                if (s[i] == ']')
                {
                    i++;
                    break;
                }

                if (s[i] == ',')
                {
                    i++;
                    continue;
                }

                result.Add(ParseValue(s, ref i));
            }

            return result;
        }

        private static string ParseString(string s, ref int i)
        {
            SkipWhitespace(s, ref i);
            if (i >= s.Length || s[i] != '"')
            {
                return null;
            }

            i++;
            var builder = new StringBuilder();
            while (i < s.Length)
            {
                char c = s[i];
                if (c == '\\')
                {
                    i++;
                    if (i >= s.Length)
                    {
                        break;
                    }

                    char escape = s[i];
                    switch (escape)
                    {
                        case 'n': builder.Append('\n'); break;
                        case 't': builder.Append('\t'); break;
                        case 'r': builder.Append('\r'); break;
                        case 'b': builder.Append('\b'); break;
                        case 'f': builder.Append('\f'); break;
                        case 'u':
                            if (i + 4 < s.Length)
                            {
                                string hex = s.Substring(i + 1, 4);
                                int code;
                                if (int.TryParse(hex, System.Globalization.NumberStyles.HexNumber,
                                        System.Globalization.CultureInfo.InvariantCulture, out code))
                                {
                                    builder.Append((char)code);
                                    i += 4;
                                }
                            }

                            break;
                        default:
                            builder.Append(escape);
                            break;
                    }

                    i++;
                    continue;
                }

                if (c == '"')
                {
                    i++;
                    break;
                }

                builder.Append(c);
                i++;
            }

            return builder.ToString();
        }

        private static object ParseNumber(string s, ref int i)
        {
            int start = i;
            while (i < s.Length && (char.IsDigit(s[i]) || s[i] == '-' || s[i] == '+' || s[i] == '.' ||
                                    s[i] == 'e' || s[i] == 'E'))
            {
                i++;
            }

            string token = s.Substring(start, i - start);
            double value;
            if (double.TryParse(token, System.Globalization.NumberStyles.Float,
                    System.Globalization.CultureInfo.InvariantCulture, out value))
            {
                return value;
            }

            return null;
        }

        private static void SkipWhitespace(string s, ref int i)
        {
            while (i < s.Length && char.IsWhiteSpace(s[i]))
            {
                i++;
            }
        }
    }
}
