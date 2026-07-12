# Mango LWT Recorder

A small offline-first research data collection app written in Python/Kivy.

## Data format

The on-screen fields are:

- Block
- TreeID
- PanicleID
- L (mm)
- W (mm)
- T (mm)

Exported CSV columns:

```text
Block,TreeID,PanicleID,L,W,T,Timestamp
```

Data is saved immediately to a local SQLite database. Block and TreeID remain unchanged after saving. A numeric PanicleID automatically increases by one.

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
cp /mnt/c/Users/Folder_To_Downloads/mango_lwt_recorder_kivy/mango_lwt_recorder/main.py ~/mango_lwt_recorder/main.py
cp /mnt/c/Users/Folder_To_Downloads/mango_lwt_recorder_kivy/mango_lwt_recorder/buildozer.spec ~/mango_lwt_recorder/buildozer.spec
cd ~/mango_lwt_recorder
python3 -m venv .venv
source .venv/bin/activate
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

Tap an input field and use the phone keyboard's microphone. Press the keyboard's Return/Next key to advance. After entering T, Return saves the row. Dictation itself cannot issue a real Tab command, so this app is designed around Return/Next and a large `SAVE & NEXT` button.

## Current limitations

- CSV export writes to Downloads, but there is no native share sheet yet.
- It does not perform offline speech recognition independently; it accepts text from the phone's available keyboard dictation.
- It has no record editing screen yet, but `UNDO LAST` removes the most recent row.

## Suggested next upgrade

Add a history/edit screen and native share sheet using `plyer` or platform-specific APIs. Fully offline speech recognition is possible but makes mobile packaging significantly larger and more complex.
