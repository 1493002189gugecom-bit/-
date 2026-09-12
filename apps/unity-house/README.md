# Unity House — Phase C

Three-room virtual house driven by the authoritative home service. The Unity
client is a **view**: it never decides or mutates state on its own.

## Editor version

**Unity 2022.3.47f1c1** (fixed by user preference; the editor and the
`windowsstandalone` module are installed at `D:\unity\edition`). This is the
target version, not a fallback from a newer one.

## Open the project

1. Start the home service first:

   ```powershell
   .\.venv\Scripts\python.exe apps/home-service/src/server.py --port 8765
   ```

2. In Unity Hub, **Add** the folder `apps/unity-house` and open it with
   2022.3.47f1c1. Unity will generate `Library/`, `Temp/` and `Logs/`, which are
   git-ignored.

3. If prompted about the API compatibility level, keep **.NET Standard 2.1**.

## Verify connectivity (Phase C step 1)

Two complementary checks:

**a) Offline parser check (no editor needed)**

```powershell
dotnet run --project tools/unity-check/unity-check.csproj
```

This compiles the real `StateParser.cs` / `MiniJson.cs` with the .NET SDK and
validates them against a captured service payload. See
`tools/unity-check/README.md`.

**b) In-editor check**

Create an empty scene, add an empty GameObject, attach `ConnectivityCheck.cs`,
press Play. The on-screen report states:

- Unity version and API compatibility level
- whether `/health` and `/snapshot` are reachable
- how many rooms/devices/persons were parsed
- whether WebSocket support is available in this build

A screenshot of that report is the evidence for step 1.

## Scripts

| Script | Role |
| --- | --- |
| `StateParser.cs` | Dependency-free JSON reader for the service payload |
| `HomeServiceClient.cs` | Loopback HTTP sync (snapshot + increments) and receipt reporting |
| `SceneStateApplier.cs` | Applies state to primitives; drives the broadcast highlight |
| `ConnectivityCheck.cs` | Step 1 verification and on-screen report |
| `Tests/StateParserTests.cs` | Unity Test Framework tests using a real payload |

## State semantics the view must respect

- **Unknown location looks unknown.** A person with `location_known == false` is
  drawn distinctly and is never left at a stale position.
- **Offline devices look offline.** A device with `online == false` is greyed and
  its state is not presented as live.
- **Only one room broadcasts at a time.** The highlight follows the queue head;
  `played`, `failed` and `cancelled` tasks are skipped.
- **Room name travels with the task.** Highlighting uses `room_name` from the
  payload, so a label can never point at the wrong room.

Camera detections never move these objects; positions come only from the state
service.

## Tracked vs generated

Tracked: `Assets/`, `Packages/`, `ProjectSettings/`, this README, and the
project `.gitignore`. Generated and ignored: `Library/`, `Temp/`, `Obj/`,
`Build/`, `Builds/`, `Logs/`, `UserSettings/`, `.vs/`.
