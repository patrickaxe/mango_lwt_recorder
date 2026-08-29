# Mango LWT Recorder

A small offline-first research data collection app written in Python/Kivy.

## Data format

The on-screen fields are:

- Block
- TreeID
- PanicleID
- Cultivar (`Calypso` or `Other`)
- L (mm)
- W (mm)
- T (mm)
- Weight (g)
- Brix (°)
- SamplingRole (`Core`, `Reserve`, `Destructive`, `Observation`, or `Drop`)
- Comment (optional)

Two collection modes are available:

- **LWT only**: pressing Return/Data after T validates and saves the record,
  increments a numeric PanicleID, vibrates briefly on Android, and returns focus
  to L for the next fruit.
- **LWT + Weight + Brix**: retains the complete field sequence and saves after
  Brix.

The selected mode is remembered between sessions. LWT-only mode requires all
three dimensions except when SamplingRole is `Drop`, which can be saved without
L/W/T so naturally dropped, damaged, missing, or otherwise discontinued fruit can
be recorded in the field. Dimension values must be in the existing valid range.
For `Calypso`, shape validation checks `0.5 <= T/L <= 1.0` and
`0.5 <= T/W <= 1.1`. For `Other`, the existing `L >= W >= T` orientation
check is retained.

SamplingRole defaults to `Core` and is retained after SAVE & NEXT to make repeated
cohort measurements fast. Comment is optional and is cleared after each saved
record.

Exported CSV columns:

```text
Block,TreeID,PanicleID,Cultivar,L,W,T,Weight,Brix,SamplingRole,Comment,Timestamp
```

Data is saved immediately to a local SQLite database. Partially completed rows
can be saved as long as at least one field has a value; only populated numeric
fields are validated. Block and TreeID remain unchanged after saving. A numeric
PanicleID automatically increases by one. Existing local databases are migrated
in place by adding nullable SamplingRole, Comment, and Cultivar columns, so older
records remain readable and export with blank values for fields that did not exist
when they were recorded.

Records are grouped into worksheets. The worksheet selector changes the active
worksheet; record counts, `UNDO LAST`, and CSV export apply only to the active
worksheet. Use `NEW` to create and name a fresh worksheet without deleting the
older worksheets.

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
mkdir mango_lwt_recorder
cd mango_lwt_recorder
cp /mnt/c/Users/Folder_To_Downloads/mango_lwt_recorder/main.py ~/mango_lwt_recorder/main.py
cp /mnt/c/Users/Folder_To_Downloads/mango_lwt_recorder/buildozer.spec ~/mango_lwt_recorder/buildozer.spec
sudo apt update && sudo apt install python3.12-venv # only use for the first time user
python3 -m venv .venv # only use for the first time user
source .venv/bin/activate
pip install buildozer # only use for the first time user
buildozer android debug
```



The APK will appear in the `bin/` directory. For release distribution, configure signing and build an AAB.

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
After pulling voice-control changes, use a clean build so the Java source is added
to the APK:

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
