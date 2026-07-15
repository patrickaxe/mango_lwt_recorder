[app]
title = Mango LWT Recorder
package.name = mangolwtrecorder
package.domain = au.edu.research
source.dir = .
source.include_exts = py,java,png,jpg,kv,atlas,csv,xml
version = 0.2.2
requirements = python3,kivy,pyjnius
orientation = portrait
fullscreen = 0

# Android
android.api = 35
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
android.permissions = READ_EXTERNAL_STORAGE, WRITE_EXTERNAL_STORAGE, RECORD_AUDIO
android.extra_manifest_xml = ./src/android/extra_manifest.xml
android.add_src = src/android/java

# The app itself requests no INTERNET permission. Android's installed speech
# recognition service may still use its own network access when on-device
# recognition is unavailable. Storage permissions retain older-device CSV export.

[buildozer]
log_level = 2
warn_on_root = 1
