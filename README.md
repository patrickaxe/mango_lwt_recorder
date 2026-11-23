# Mango LWT Recorder

A small offline-first research data collection app written in Python/Kivy.

## Data format

The on-screen fields are:

- Block (required)
- TreeID (required)
- PanicleID (required)
- Cultivar (`Calypso` or `Other`, optional)
- L (mm)
- W (mm)
- T (mm)
- k (custom weight factor)
- Weight (g)
- Predicted_Weight (g, calculated)
- Brix (°)
- SamplingRole (`Core`, `Reserve`, `Destructive`, `Observation`, `Drop`, or
  `Replaced`; optional)
- Comment (optional)
- Longitude (automatic, decimal degrees)
- Latitude (automatic, decimal degrees)
- GNSS quality (automatic receiver fix-quality code)
- GNSS status

Four collection modes are available:

- **LWT only**: pressing Return/Data after T validates and saves the record,
  increments a numeric PanicleID, vibrates briefly on Android, and returns focus
  to L for the next fruit.
- **Weight only**: enables the measured Weight field and saves after Weight.
- **Brix only**: enables the Brix field and saves after Brix.
- **LWT + Weight + Brix**: retains the complete field sequence and saves after
  Brix.

The selected mode is remembered between sessions. Fields that do not belong to
the selected mode are disabled and skipped by keyboard and voice navigation.
Block, TreeID, and PanicleID must be present on every saved record. All other
enabled fields are optional. Populated dimension values must be in the existing
valid range. When all three dimensions are present, `Calypso` shape validation checks
`0.5 <= T/L <= 1.0` and `0.5 <= T/W <= 1.1`; `Other` uses the existing
`L >= W >= T` orientation check.

The custom `k` value is remembered between sessions and retained when moving to
the next fruit. When `k`, L, W, and T are all positive numbers, the app fills and
saves `Predicted_Weight` automatically using
`Predicted_Weight = k * L * W * T / 1000`. The original Weight field remains available
for manual measured-weight entry.

The main collection page also shows a persistent summary containing the current
TreeID and PanicleID. Its measurement and Mean follow the selected mode:
Predicted Weight for **LWT only**, Weight for **Weight only**, and Brix for
**Brix only**. **LWT + Weight + Brix** displays all three measurements and their
separate Means. Each Mean uses only saved, nonblank values from its matching
field in the active worksheet. The display refreshes after edits, saves,
undo/delete operations, mode changes, and worksheet changes.

SamplingRole defaults to `Core` and is retained after SAVE & NEXT to make repeated
cohort measurements fast. Comment is optional and is cleared after each saved
record.

Exported CSV columns:

```text
Block,TreeID,PanicleID,Cultivar,L,W,T,Weight,Predicted_Weight,Brix,SamplingRole,Comment,Timestamp,Longitude,Latitude,GNSS quality
```

On Android, saving a record captures the phone's latest fresh GNSS position along
with the save timestamp. Grant **precise location** permission and enable device
location services. The form displays the current automatic values and GNSS
status; no extra typing is required. Position updates run while the app is in the
foreground and stop when it is paused or closed.

If the coordinate fields stay blank, check **GNSS status** and tap **RETRY GNSS**.
It checks location permission again and restarts the receiver. Microphone and
location permission dialogs are requested separately to avoid a canceled request
leaving GNSS stuck. Saving on Android reports **GNSS saved** when the record
contains coordinates, or **GNSS blank** when no fresh position was available.
This does not change or backfill previously saved records.

**GNSS components missing; reinstall rebuilt APK** means the installed package
does not contain the location Java files. Copy the complete source and perform
the clean build below. **Waiting for GNSS fix** means location updates have been
requested but a fresh satellite position has not arrived yet. **Allow precise
location...** means precise location permission is still required.

`GNSS quality` is the receiver's NMEA GGA fix-quality code, not an accuracy in
metres. Common codes are `1` (GNSS fix), `2` (differential fix), `4` (RTK fixed),
and `5` (RTK float). Quality is saved only when the receiver reports a matching
GGA fix. A phone that does not expose GGA can still save longitude and latitude
with blank quality. Fixes older than 10 seconds are discarded. Missing location
permission, an unavailable/stale fix, or a device without GNSS leaves the
unavailable values blank and does not prevent measurement collection. Desktop
and iOS currently leave these automatic GNSS fields blank.

Data is saved immediately to a local SQLite database. Only populated numeric
fields are validated. In a manual worksheet, Block and TreeID remain unchanged
after saving and a numeric PanicleID automatically increases by one. Existing
local databases are migrated in place, so older records remain readable and
export with blank values for fields that did not exist when they were recorded.

Records are grouped into worksheets. The worksheet selector changes the active
worksheet; record counts, `UNDO LAST`, and CSV export apply only to the active
worksheet. Use `NEW` to create and name a fresh worksheet without deleting the
older worksheets.

## Worksheet templates

Tap **IMPORT CSV** to create a worksheet from a CSV template. A valid template
must have `Block`, `TreeID`, and `PanicleID` columns, and every nonblank row must
contain values for those three fields. The remaining supported columns are
optional: `Cultivar`, `L`, `W`, `T`, `Weight`, `Brix`, `SamplingRole`, and
`Comment`. `Timestamp`, `Longitude`, `Latitude`, and `GNSS quality` columns are
allowed but ignored: the app captures the save time and current phone GNSS data
when each measurement is saved.

Template rows are not counted as collected measurements. The app displays and
prefills the next unfinished template row; **SAVE & NEXT** records it and advances
to the next row. Undoing a template record makes that row available again.

Use **ADD ROW** in the Template menu to enter a fruit that was missing from an
imported CSV. The extra fruit is saved in the current worksheet without consuming
the pending template row, and the app resumes the next unfinished template row
after the extra row is saved. On a manual worksheet, **ADD ROW** simply clears
the form for a new record.

`FruitSizingTemp.csv` is bundled with the app as an example. Tap **USE EXAMPLE**
to create a new worksheet from it. Importing a template is optional; ordinary
worksheets continue to support manual collection.

CSV exports are saved to the device Downloads folder. On Android this is:

```text
/storage/emulated/0/Download/
```

## Run on a computer first

Python 3.11 or 3.12 is recommended.

```bash
python -m venv .venv
```

Activate the environment, then:

```bash
pip install -r requirements.txt
python main.py
```

## Android build

Buildozer/python-for-android is normally built on Linux. On Windows, use WSL2 with Ubuntu.

```bash
pip install buildozer
sudo apt update
sudo apt install -y git zip unzip openjdk-17-jdk python3-pip \
  autoconf libtool pkg-config zlib1g-dev libncurses5-dev \
  libncursesw5-dev cmake libffi-dev libssl-dev
buildozer android debug
```

```bash
mkdir -p ~/mango_lwt_recorder
cd ~/mango_lwt_recorder
APP_SOURCE=/mnt/c/Users/Patrick/Documents/GitHub/mango_lwt_recorder
cp "$APP_SOURCE"/{main.py,gnss.py,template_csv.py,validate_android_source.py,repair_android_pip.py,buildozer.spec,FruitSizingTemp.csv} .
cp -R "$APP_SOURCE/src" .
sudo apt update && sudo apt install python3.12-venv # only use for the first time user
python3 -m venv .venv # only use for the first time user
source .venv/bin/activate
pip install buildozer # only use for the first time user
python3 validate_android_source.py
buildozer android clean
buildozer android debug
```

Adjust `APP_SOURCE` if the Windows checkout is in a different directory. Always
copy all listed files and the complete `src` directory to a separate WSL build
directory. Copying only `main.py` and `buildozer.spec` omits the GNSS Python module
and Java classes. The source validation command checks for these files and both
location permissions; fix any reported errors before building. A clean build is
required after Java or permission changes so they are included in the new APK.

The APK will appear in the `bin/` directory. For release distribution, configure signing and build an AAB.

If a dependency download fails with `curl 92 HTTP/2`, `early EOF`, or
`fetch-pack: invalid index-pack output`, resume from the activated WSL project
directory using HTTP/1.1 for that build's Git subprocesses:

```bash
env GIT_CONFIG_COUNT=1 \
    GIT_CONFIG_KEY_0=http.version \
    GIT_CONFIG_VALUE_0=HTTP/1.1 \
    buildozer android debug
```

This keeps the existing build cache and applies the HTTP setting only to this
command. A continued `Connection reset by peer` indicates the transfer is still
being interrupted. The available HTTP versions and command-scoped environment
configuration are described in the [Git configuration documentation](https://git-scm.com/docs/git-config).

If a Python 3.14 build fails with `cannot import name 'capture_logging'`, the
temporary build environment may contain mixed pip versions. The current p4a
bootstrap can overlay its bundled pip when recreating an existing environment.
After the failed build has exited, run:

```bash
python3 repair_android_pip.py
buildozer android debug
```

The helper backs up only the temporary build `venv`, recreates it with the
compiled host Python, and constrains its pip to that host's bundled version.
Native Android libraries and the project's `.venv` are retained. It also fixes
the known target-wheel install command to use the same Android platform tags as
dependency resolution, preventing Android wheels from being checked against the
Linux host platform. The original toolchain file and environment are preserved
under `.buildozer/pip-recovery-backups`. The helper refuses to run alongside an
active build or against an unrecognized install-command layout. A full clean
removes the temporary pip configuration; rerun the helper if the issue returns.

## iOS build

An iOS build requires macOS, Xcode, an Apple developer setup, and the `kivy-ios` toolchain.

Typical outline:

```bash
python3 -m pip install kivy-ios
toolchain build python3 kivy
toolchain create MangoLWT /absolute/path/to/mango_lwt_recorder
open mangoLWT-ios/MangoLWT.xcodeproj
```

The exact generated directory/project name can vary. Complete signing, bundle ID and deployment settings in Xcode.

## Using iPhone/Android dictation

Tap an input field and use the phone keyboard's microphone. Press the keyboard's
Return/Next key to advance. After entering Brix, Return saves the row. Dictation
itself cannot issue a real Tab command, so the app also provides Android voice
control and a large `SAVE & NEXT` button.

### Android voice-control session

Tap **START VOICE** and grant microphone permission. While the button says
**STOP VOICE**, each completed utterance is recognized and the app automatically
starts listening for the next utterance.

- Speak a value to enter it into the currently selected field. English number
  phrases such as **“twenty five point six”** are converted to `25.6` for numeric
  fields.
- Say **“next field”** to move to the next input field.
- Say **“next fruit”** (or **“save and next”**) to run `SAVE & NEXT`. A partial
  record is allowed; only a completely blank row is rejected.
- Say **“delete last record”** to open the existing deletion confirmation.
- Say **“stop listening”**, or tap **STOP VOICE**, to finish the session.

Android's system `SpeechRecognizer` handles this mode. Depending on the phone and
its installed recognition service, processing may occur on-device or may use a
network connection. Android does not define this API as a permanent always-on
listener, so the app implements the session by restarting recognition after each
result or silence timeout. Stop the session when it is not needed to reduce
battery use.

On iPhone and desktop, the Voice control text box remains available as a fallback:
type a command, or use the iPhone keyboard microphone and then press Return.

The Android speech result listener includes a small Java-to-Python string bridge.
After pulling voice-control or GNSS changes, use a clean build so the Java source
and location permissions are added to the APK:

```bash
buildozer android clean
buildozer android debug
```

### Voice-actuated delete

1. Start Android voice control, or tap the **Voice control** field and use the
   phone keyboard's microphone.
2. Say **“delete last record”** (or **“delete the last record”**).
3. Check the displayed Block, Tree, and Panicle, then tap **DELETE** to confirm.

The command deletes only the most recent record in the active worksheet. The
confirmation prevents an accidental dictation match from deleting data.

### Worksheet and history controls

- Select an existing worksheet from the **Worksheet** menu.
- Tap **NEW** to name and create an empty worksheet while preserving all older
  worksheets.
- Tap **DELETE ALL HISTORY** to permanently remove every saved record and
  worksheet. A confirmation shows the number of affected records and worksheets;
  after deletion, the app creates a new empty `Worksheet 1`.

## Current limitations

- CSV export writes to Downloads, but there is no native share sheet yet.
- Voice recognition depends on Android's installed recognition service or the
  phone keyboard; on-device/offline recognition availability varies by device.
- It has no record editing screen yet, but `UNDO LAST` removes the most recent row.

## Suggested next upgrade

Add a history/edit screen and native share sheet using `plyer` or platform-specific APIs. Fully offline speech recognition is possible but makes mobile packaging significantly larger and more complex.
