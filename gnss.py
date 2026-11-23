"""Fresh phone GNSS fixes without importing Android or Kivy on desktop.

The app requests precise foreground location permission before ``start()`` and
calls ``stop()`` when paused. Both methods may be called on the Kivy thread;
Android listener registration is dispatched to its main looper by the bridge.
``snapshot()`` is thread safe and never returns coordinates older than 10 seconds.
GNSS quality is the raw NMEA GGA fix-quality integer, not horizontal accuracy.
It remains unknown when the phone does not expose a matching GGA sentence.
"""

from __future__ import annotations

import math
import re
import threading
import time
import traceback
from dataclasses import dataclass


GNSS_COMPONENTS_MISSING = "GNSS components missing; reinstall rebuilt APK"
GNSS_START_FAILED = "Could not start GNSS; tap RETRY GNSS"


class GnssInitializationError(RuntimeError):
    """An initialization failure with a concise, actionable display status."""

    def __init__(self, message, *, status=GNSS_START_FAILED):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class GnssSnapshot:
    longitude: float | None = None
    latitude: float | None = None
    gnss_quality: int | None = None
    status: str = "Waiting for GNSS fix"


@dataclass(frozen=True)
class _Gga:
    longitude: float | None
    latitude: float | None
    quality: int
    utc_seconds: float


def _coordinate(value, direction, *, latitude):
    degrees_length = 2 if latitude else 3
    if not re.fullmatch(r"\d{%d}(?:\.\d+)?" % (degrees_length + 2), value):
        raise ValueError("Invalid NMEA coordinate")
    degrees = int(value[:degrees_length])
    minutes = float(value[degrees_length:])
    maximum = 90 if latitude else 180
    if minutes >= 60 or degrees > maximum or (degrees == maximum and minutes):
        raise ValueError("NMEA coordinate outside WGS84 bounds")
    if direction not in ("NS" if latitude else "EW") or len(direction) != 1:
        raise ValueError("Invalid NMEA hemisphere")
    result = degrees + minutes / 60.0
    return -result if direction in "SW" else result


def parse_gga(sentence):
    """Return a validated GGA fix, or None for corrupt/other NMEA sentences."""
    try:
        sentence = sentence.strip()
        if not sentence.startswith("$") or sentence.count("*") != 1:
            return None
        payload, checksum = sentence[1:].split("*")
        if not re.fullmatch(r"[0-9a-fA-F]{2}", checksum):
            return None
        expected = 0
        for character in payload:
            expected ^= ord(character)
        if expected != int(checksum, 16):
            return None
        fields = payload.split(",")
        if len(fields) < 7 or not re.fullmatch(r"[A-Z]{2}GGA", fields[0]):
            return None
        if not re.fullmatch(r"\d{6}(?:\.\d+)?", fields[1]):
            return None
        hours, minutes, seconds = (
            int(fields[1][:2]), int(fields[1][2:4]), float(fields[1][4:])
        )
        if hours >= 24 or minutes >= 60 or seconds >= 60:
            return None
        if not re.fullmatch(r"[0-8]", fields[6]):
            return None
        quality = int(fields[6])
        longitude = latitude = None
        if quality:
            latitude = _coordinate(fields[2], fields[3], latitude=True)
            longitude = _coordinate(fields[4], fields[5], latitude=False)
        return _Gga(longitude, latitude, quality, hours * 3600 + minutes * 60 + seconds)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def _distance_metres(lon1, lat1, lon2, lat2):
    lat1, lat2 = math.radians(lat1), math.radians(lat2)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(lon2 - lon1)
    haversine = math.sin(delta_lat / 2) ** 2 + (
        math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 6371000.0 * 2 * math.asin(min(1.0, math.sqrt(haversine)))


class GnssController:
    """Cache a fresh GPS location with GGA quality from the same fix.

    ``provider`` and ``clock`` are injectable for deterministic tests. A provider
    has ``start(on_location, on_nmea, on_status)`` and ``stop()``. The callbacks
    accept respectively ``(lon, lat, unix_fix_ms, age_seconds)``,
    ``(sentence, unix_fix_ms)``, and a readable status string. Android imports
    and the Java bridge are created lazily, only when ``android=True``.
    """

    MAX_AGE_SECONDS = 10.0
    MATCH_TIME_MS = 500
    MATCH_DISTANCE_METRES = 20.0
    _BLOCKED_STATUSES = {
        "Location services disabled",
        "Precise location permission required",
        "GNSS unavailable on this device",
        GNSS_COMPONENTS_MISSING,
        GNSS_START_FAILED,
    }
    _TERMINAL_STATUSES = _BLOCKED_STATUSES - {"Location services disabled"}

    def __init__(self, *, android=False, provider=None, clock=time.monotonic):
        self._provider = provider
        self._android = android
        self._clock = clock
        self._lock = threading.RLock()
        self._running = False
        self._generation = 0
        self._location = None
        self._gga = None
        self._last_error = None
        self._status = (
            "Waiting for GNSS fix" if android or provider is not None
            else "GNSS unavailable on this device"
        )

    @property
    def last_error(self):
        """Detailed startup traceback for diagnostics; not intended as UI copy."""
        with self._lock:
            return self._last_error

    @property
    def is_running(self):
        with self._lock:
            return self._running

    def start(self):
        """Begin foreground updates after precise location permission is granted."""
        with self._lock:
            if self._running:
                return
            if self._provider is None and not self._android:
                return
            self._generation += 1
            generation = self._generation
            self._running = True
            self._location = self._gga = None
            self._last_error = None
            self._status = "Waiting for GNSS fix"
            try:
                if self._provider is None:
                    self._provider = _AndroidProvider()
                self._provider.start(
                    lambda *args: self._on_location(generation, *args),
                    lambda *args: self._on_nmea(generation, *args),
                    lambda status: self._on_status(generation, status),
                )
            except Exception as error:
                self._last_error = traceback.format_exc()
                traceback.print_exc()
                self._generation += 1
                self._running = False
                self._location = self._gga = None
                self._status = (
                    error.status if isinstance(error, GnssInitializationError)
                    else GNSS_START_FAILED
                )
                if self._provider is not None:
                    try:
                        self._provider.stop()
                    except Exception:
                        traceback.print_exc()

    def stop(self):
        """Invalidate cached data immediately and unregister Android listeners."""
        with self._lock:
            self._generation += 1
            self._running = False
            self._location = self._gga = None
            if self._provider is not None:
                self._status = "GNSS paused"
                try:
                    self._provider.stop()
                except Exception:
                    traceback.print_exc()

    def _on_location(self, generation, longitude, latitude, fix_ms, age_seconds):
        with self._lock:
            if not self._running or generation != self._generation:
                return
            if self._status in self._BLOCKED_STATUSES:
                return
            try:
                lon, lat = float(longitude), float(latitude)
                fix_ms, age = float(fix_ms), float(age_seconds)
                if not all(math.isfinite(v) for v in (lon, lat, fix_ms, age)):
                    return
                if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    return
                if not (0 <= age <= self.MAX_AGE_SECONDS) or fix_ms <= 0:
                    return
                if self._location and fix_ms < self._location[2]:
                    return
                self._location = (lon, lat, fix_ms, self._clock() - age)
                self._status = "Waiting for GNSS fix"
            except (TypeError, ValueError, OverflowError):
                return

    def _on_nmea(self, generation, sentence, fix_ms):
        with self._lock:
            if not self._running or generation != self._generation:
                return
            if self._status in self._BLOCKED_STATUSES:
                return
            gga = parse_gga(sentence)
            if gga is None:
                return
            try:
                fix_ms = float(fix_ms)
                if not math.isfinite(fix_ms) or fix_ms <= 0:
                    return
                # Check the sentence's UTC as well as Android's fix timestamp.
                # The circular difference handles fixes on either side of UTC midnight.
                utc_difference = abs((fix_ms / 1000) % 86400 - gga.utc_seconds)
                if min(utc_difference, 86400 - utc_difference) > self.MATCH_TIME_MS / 1000:
                    return
                if self._gga and fix_ms < self._gga[1]:
                    return
                self._gga = (gga, fix_ms, self._clock())
            except (TypeError, ValueError, OverflowError):
                return

    def _on_status(self, generation, status):
        with self._lock:
            if not self._running or generation != self._generation:
                return
            self._status = str(status)
            if status in self._BLOCKED_STATUSES:
                self._location = self._gga = None
            if status in self._TERMINAL_STATUSES:
                # Registration completes on Android's main thread. A failed
                # registration must not leave start() permanently idempotent.
                # Invalidate its callbacks before allowing a new attempt.
                self._generation += 1
                self._running = False
                if status == GNSS_START_FAILED:
                    self._last_error = (
                        "Android GNSS registration failed; the MangoGnss log "
                        "contains the Java exception and stack trace."
                    )

    def snapshot(self):
        """Return fresh coordinates and an optional matching raw GGA quality code."""
        with self._lock:
            now = self._clock()
            location, quality = self._location, None
            gga = self._gga
            if gga and not 0 <= now - gga[2] <= self.MAX_AGE_SECONDS:
                gga = None
            if location and not 0 <= now - location[3] <= self.MAX_AGE_SECONDS:
                location = None
            if gga and gga[0].quality == 0 and (
                location is None or gga[1] >= location[2] - self.MATCH_TIME_MS
            ):
                return GnssSnapshot(gnss_quality=0, status="No GNSS fix")
            if location is None:
                status = self._status
                if self._location and status not in self._BLOCKED_STATUSES:
                    status = "GNSS fix expired; waiting for a fresh fix"
                return GnssSnapshot(status=status)
            lon, lat, fix_ms, _received = location
            if gga and gga[0].quality and abs(gga[1] - fix_ms) <= self.MATCH_TIME_MS:
                fix = gga[0]
                if _distance_metres(lon, lat, fix.longitude, fix.latitude) <= self.MATCH_DISTANCE_METRES:
                    quality = fix.quality
            status = (
                "GNSS fix available" if quality is not None
                else "GNSS fix available; GGA quality unavailable"
            )
            return GnssSnapshot(lon, lat, quality, status)


class _AndroidProvider:
    """Keep Android objects and listener lifetimes outside the UI layer."""

    def __init__(self):
        try:
            from jnius import PythonJavaClass, autoclass, java_method
        except ImportError as error:
            raise GnssInitializationError(
                "The APK is missing the required PyJNIus runtime",
                status=GNSS_COMPONENTS_MISSING,
            ) from error

        # Check custom classes before proxy construction so an APK built without
        # src/android/java reports a packaging problem, not missing GNSS hardware.
        try:
            Bridge = autoclass("org.mango.recorder.location.GnssLocationBridge")
            autoclass("org.mango.recorder.location.GnssCallback")
        except Exception as error:
            description = (
                str(error) + " " + str(getattr(error, "classname", ""))
            ).lower()
            missing = any(marker in description for marker in (
                "classnotfoundexception", "noclassdeffounderror", "class not found",
                "unable to find the class", "unable to found the class",
            ))
            if missing:
                raise GnssInitializationError(
                    "The APK is missing the GNSS Java classes from src/android/java",
                    status=GNSS_COMPONENTS_MISSING,
                ) from error
            raise

        provider = self

        class Callback(PythonJavaClass):
            __javainterfaces__ = ["org/mango/recorder/location/GnssCallback"]
            __javacontext__ = "app"

            @java_method("(DDJDJ)V")
            def onLocation(self, longitude, latitude, fix_ms, age_seconds, generation):
                provider._emit(generation, 0, longitude, latitude, fix_ms, age_seconds)

            @java_method("(Ljava/lang/String;JJ)V")
            def onNmea(self, sentence, fix_ms, generation):
                provider._emit(generation, 1, str(sentence), fix_ms)

            @java_method("(Ljava/lang/String;J)V")
            def onStatus(self, status, generation):
                provider._emit(generation, 2, str(status))

        self._generation = 0
        self._callbacks = ()
        self._callback = Callback()
        Activity = autoclass("org.kivy.android.PythonActivity")
        self._bridge = Bridge(Activity.mActivity, self._callback)

    def _emit(self, generation, index, *values):
        try:
            callbacks = self._callbacks
            if generation == self._generation and callbacks:
                callbacks[index](*values)
        except Exception:
            # Exceptions must never propagate back across a JNI callback.
            traceback.print_exc()

    def start(self, on_location, on_nmea, on_status):
        self._generation += 1
        self._callbacks = (on_location, on_nmea, on_status)
        self._bridge.start(self._generation)

    def stop(self):
        self._generation += 1
        self._callbacks = ()
        self._bridge.stop()
