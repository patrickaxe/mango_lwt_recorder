[app]
title = Mango LWT Recorder
package.name = mangolwtrecorder
package.domain = au.edu.research
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,csv
version = 0.1.0
requirements = python3,kivy
orientation = portrait
fullscreen = 0

# Android
android.api = 35
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
android.permissions = READ_EXTERNAL_STORAGE, WRITE_EXTERNAL_STORAGE

# No network permission is requested: the app is offline-first.
# Storage permission keeps CSV export compatible with older Android versions.

[buildozer]
log_level = 2
warn_on_root = 1
