"""Check that a copied project contains the sources needed for an Android build."""

import argparse
import configparser
import sys
from pathlib import Path


REQUIRED_FILES = (
    "main.py",
    "gnss.py",
    "template_csv.py",
    "FruitSizingTemp.csv",
    "buildozer.spec",
    "src/android/extra_manifest.xml",
    "src/android/java/org/mango/recorder/speech/SpeechCallback.java",
    "src/android/java/org/mango/recorder/speech/SpeechRecognitionListener.java",
    "src/android/java/org/mango/recorder/location/GnssCallback.java",
    "src/android/java/org/mango/recorder/location/GnssLocationBridge.java",
)


def validate_source(source_dir):
    source_dir = Path(source_dir).resolve()
    errors = []
    for relative_path in REQUIRED_FILES:
        path = source_dir / relative_path
        if not path.is_file():
            errors.append(f"Missing required file: {relative_path}")
        elif path.suffix == ".py":
            try:
                compile(path.read_bytes(), str(path), "exec")
            except (OSError, SyntaxError, UnicodeError) as error:
                errors.append(f"Invalid Python source {relative_path}: {error}")

    spec_path = source_dir / "buildozer.spec"
    if spec_path.is_file():
        spec = configparser.ConfigParser(interpolation=None)
        try:
            spec.read_string(spec_path.read_text(encoding="utf-8-sig"))
            if not spec.has_section("app"):
                errors.append("buildozer.spec: missing [app] section")
            else:
                permissions = {
                    item.strip().removeprefix("android.permission.")
                    for item in spec.get("app", "android.permissions", fallback="").split(",")
                }
                for permission in ("ACCESS_FINE_LOCATION", "ACCESS_COARSE_LOCATION"):
                    if permission not in permissions:
                        errors.append(f"buildozer.spec: android.permissions missing {permission}")
                java_dir = (source_dir / "src/android/java").resolve()
                java_sources = spec.get("app", "android.add_src", fallback="").split(",")
                if not any(
                    item.strip() and (source_dir / item.strip()).resolve() == java_dir
                    for item in java_sources
                ):
                    errors.append("buildozer.spec: android.add_src must include src/android/java")
        except (OSError, UnicodeError, configparser.Error) as error:
            errors.append(f"Cannot read buildozer.spec: {error}")
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", nargs="?", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args(argv)
    errors = validate_source(args.source_dir)
    if errors:
        print("Android source validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("Android source validation passed: required Python and Android Java files are present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
