using System;
using System.IO;
using System.Text;
using NUnit.Framework;

namespace SmartHome.Tests
{
    /// <summary>
    /// Parser tests. These compare against a real payload captured from the home
    /// service so a change in the service contract shows up here.
    /// </summary>
    public sealed class StateParserTests
    {
        private static string PayloadPath
        {
            get { return Path.Combine(AppContext.BaseDirectory, "snapshot.json"); }
        }

        private static string LoadPayload()
        {
            Assert.IsTrue(File.Exists(PayloadPath), "missing fixture: " + PayloadPath);
            return File.ReadAllText(PayloadPath, Encoding.UTF8);
        }

        [Test]
        public void ParsesRoomsDevicesAndPersons()
        {
            HomeSnapshot snapshot = StateParser.ParseSync(LoadPayload());
            Assert.IsNotNull(snapshot);
            Assert.AreEqual(3, snapshot.rooms.Count, "expected three rooms");
            Assert.AreEqual(6, snapshot.devices.Count, "expected six devices");
            Assert.AreEqual(3, snapshot.persons.Count, "expected three people");
            Assert.IsTrue(snapshot.rooms.ContainsKey("living_room"));
            Assert.IsTrue(snapshot.devices.ContainsKey("living_room_light"));
        }

        [Test]
        public void ReadsNestedDeviceState()
        {
            HomeSnapshot snapshot = StateParser.ParseSync(LoadPayload());
            DeviceDto light = snapshot.devices["living_room_light"];
            Assert.AreEqual("light", light.type);
            Assert.AreEqual(50, light.brightness);

            DeviceDto ac = snapshot.devices["bedroom_ac"];
            Assert.AreEqual("ac", ac.type);
            Assert.AreEqual("cool", ac.mode);
            Assert.AreEqual(26f, ac.target_temp, 0.001f);
        }

        [Test]
        public void ReadsPersonLocationFlags()
        {
            HomeSnapshot snapshot = StateParser.ParseSync(LoadPayload());
            Assert.IsTrue(snapshot.persons["dad"].location_known);
            Assert.AreEqual("bedroom", snapshot.persons["dad"].room_id);
        }

        [Test]
        public void HandlesNonAsciiNames()
        {
            HomeSnapshot snapshot = StateParser.ParseSync(LoadPayload());
            Assert.AreEqual("客厅", snapshot.rooms["living_room"].name);
            Assert.AreEqual("爸爸", snapshot.persons["dad"].display_name);
        }

        [Test]
        public void HeadBroadcastSkipsFinishedTasks()
        {
            const string json = "{\"version\":4,\"broadcast_queue\":[\"a\",\"b\"]," +
                                "\"broadcasts\":[" +
                                "{\"id\":\"a\",\"room_id\":\"bedroom\",\"state\":\"played\"}," +
                                "{\"id\":\"b\",\"room_id\":\"kitchen\",\"state\":\"queued\"}]}";
            HomeSnapshot snapshot = StateParser.ParseSync(json);
            Assert.IsNotNull(snapshot.HeadBroadcast);
            Assert.AreEqual("b", snapshot.HeadBroadcast.id);
        }

        [Test]
        public void ExtractsReceiptId()
        {
            const string json = "{\"ok\":true,\"task\":{\"id\":\"bc1\",\"receipt_id\":\"receipt-9\"}}";
            Assert.AreEqual("receipt-9", StateParser.ExtractReceiptId(json));
        }

        [Test]
        public void EmptyQueueHasNoHead()
        {
            HomeSnapshot snapshot = StateParser.ParseSync("{\"version\":1,\"broadcast_queue\":[]}");
            Assert.IsNull(snapshot.HeadBroadcast);
        }
    }
}
