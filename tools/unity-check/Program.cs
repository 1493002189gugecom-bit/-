// Verifies the Unity-side JSON parser against a real home-service payload by
// compiling the actual StateParser.cs / MiniJson.cs sources with the .NET SDK.
//
// This is a logic check, not a Unity compile: it catches parser bugs but cannot
// catch Unity-API mistakes. Those are verified by opening the project in the
// editor (see tools/unity-check/README.md).
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using SmartHome;

internal static class UnityCheck
{
    private static int _failures;

    private static void Check(bool condition, string label, string detail = null)
    {
        if (condition)
        {
            Console.WriteLine("[OK  ] " + label);
            return;
        }

        _failures++;
        Console.WriteLine("[FAIL] " + label + (detail == null ? "" : " :: " + detail));
    }

    private static string FindSnapshot()
    {
        // Search upwards so the tool works from any working directory.
        DirectoryInfo dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir != null)
        {
            string candidate = Path.Combine(dir.FullName, "apps", "unity-house", "Assets", "Tests", "snapshot.json");
            if (File.Exists(candidate))
            {
                return candidate;
            }

            dir = dir.Parent;
        }

        return null;
    }

    private static int Main()
    {
        Console.OutputEncoding = Encoding.UTF8;

        string path = FindSnapshot();
        if (path == null)
        {
            Console.WriteLine("[FAIL] snapshot.json not found");
            return 2;
        }

        Console.WriteLine("fixture: " + path);
        string json = File.ReadAllText(path, Encoding.UTF8);

        HomeSnapshot snapshot;
        try
        {
            snapshot = StateParser.ParseSync(json);
        }
        catch (Exception ex)
        {
            Console.WriteLine("[FAIL] ParseSync threw: " + ex);
            return 1;
        }

        Check(snapshot != null, "parse returns a snapshot");
        if (snapshot == null)
        {
            return 1;
        }

        Check(snapshot.rooms.Count == 3, "three rooms", "got " + snapshot.rooms.Count);
        Check(snapshot.devices.Count == 6, "six devices", "got " + snapshot.devices.Count);
        Check(snapshot.persons.Count == 3, "three persons", "got " + snapshot.persons.Count);
        Check(snapshot.version > 0, "version is positive", "got " + snapshot.version);

        RoomDto living;
        Check(snapshot.rooms.TryGetValue("living_room", out living), "living_room present");
        if (living != null)
        {
            Check(living.name == "客厅", "non-ASCII room name decoded", "got '" + living.name + "'");
            Check(Math.Abs(living.simulated_temp - 28f) < 0.001f, "room temperature parsed",
                "got " + living.simulated_temp);
        }

        DeviceDto light;
        Check(snapshot.devices.TryGetValue("living_room_light", out light), "living room light present");
        if (light != null)
        {
            Check(light.type == "light", "light type parsed", "got " + light.type);
            Check(light.brightness == 50, "nested brightness parsed", "got " + light.brightness);
            Check(light.on, "nested on flag parsed");
        }

        DeviceDto ac;
        Check(snapshot.devices.TryGetValue("bedroom_ac", out ac), "bedroom ac present");
        if (ac != null)
        {
            Check(ac.mode == "cool", "nested mode parsed", "got " + ac.mode);
            Check(Math.Abs(ac.target_temp - 26f) < 0.001f, "nested temperature parsed",
                "got " + ac.target_temp);
            Check(ac.on, "ac on flag parsed");
        }

        DeviceDto kitchenLight;
        Check(snapshot.devices.TryGetValue("kitchen_light", out kitchenLight), "kitchen light present");
        if (kitchenLight != null)
        {
            Check(!kitchenLight.on, "an off device stays off");
        }

        PersonDto dad;
        Check(snapshot.persons.TryGetValue("dad", out dad), "dad present");
        if (dad != null)
        {
            Check(dad.display_name == "爸爸", "person name decoded", "got '" + dad.display_name + "'");
            Check(dad.location_known, "location_known parsed");
            Check(dad.room_id == "bedroom", "person room parsed", "got " + dad.room_id);
        }

        Check(snapshot.broadcastQueue.Count == 1, "broadcast queue parsed",
            "got " + snapshot.broadcastQueue.Count);
        BroadcastDto head = snapshot.HeadBroadcast;
        Check(head != null, "queue head resolves");
        if (head != null)
        {
            Check(head.room_name == "卧室", "head room decoded", "got " + head.room_name);
            Check(head.state == "queued", "head state parsed", "got " + head.state);
        }

        // Finished tasks must not be treated as the head.
        HomeSnapshot finished = StateParser.ParseSync(
            "{\"version\":2,\"broadcast_queue\":[\"a\",\"b\"],\"broadcasts\":[" +
            "{\"id\":\"a\",\"room_id\":\"bedroom\",\"state\":\"played\"}," +
            "{\"id\":\"b\",\"room_id\":\"kitchen\",\"state\":\"playing\"}]}");
        Check(finished.HeadBroadcast != null && finished.HeadBroadcast.id == "b",
            "played tasks are skipped when finding the head");

        HomeSnapshot empty = StateParser.ParseSync("{\"version\":1,\"broadcast_queue\":[]}");
        Check(empty.HeadBroadcast == null, "empty queue has no head");

        Check(StateParser.ExtractReceiptId("{\"task\":{\"receipt_id\":\"r-1\"}}") == "r-1",
            "receipt id extracted");

        // Escapes and unicode escapes must survive.
        HomeSnapshot escaped = StateParser.ParseSync(
            "{\"version\":1,\"rooms\":[{\"id\":\"r\",\"name\":\"\\u5ba2\\u5385\\nA\",\"simulated_temp\":1}]}");
        Check(escaped.rooms["r"].name == "客厅\nA", "unicode escape and newline decoded",
            "got '" + escaped.rooms["r"].name + "'");

        Console.WriteLine();
        Console.WriteLine(_failures == 0 ? "ALL CHECKS PASSED" : _failures + " CHECK(S) FAILED");
        return _failures == 0 ? 0 : 1;
    }
}
