package org.mango.recorder.location;

import android.content.Context;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.location.OnNmeaMessageListener;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;

/** Foreground GPS and GGA registration, compatible with Android API 24+. */
public final class GnssLocationBridge {
    private static final String TAG = "MangoGnss";
    private final Context context;
    private final GnssCallback callback;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private LocationManager manager;
    private LocationListener locationListener;
    private OnNmeaMessageListener nmeaListener;
    private volatile long requestedGeneration = -1;

    public GnssLocationBridge(Context context, GnssCallback callback) {
        this.context = context.getApplicationContext();
        this.callback = callback;
    }

    public void start(final long generation) {
        requestedGeneration = generation;
        handler.post(new Runnable() {
            @Override public void run() {
                if (requestedGeneration != generation) {
                    return;
                }
                unregister();
                try {
                    register(generation);
                } catch (SecurityException error) {
                    unregister();
                    Log.e(TAG, "GNSS registration permission denied", error);
                    status("Precise location permission required", generation);
                } catch (RuntimeException error) {
                    unregister();
                    Log.e(TAG, "GNSS registration failed", error);
                    status("Could not start GNSS; tap RETRY GNSS", generation);
                }
            }
        });
    }

    public void stop() {
        requestedGeneration = -1;
        handler.post(new Runnable() {
            @Override public void run() { unregister(); }
        });
    }

    private void status(String status, long generation) {
        if (requestedGeneration != generation || callback == null) {
            return;
        }
        try {
            callback.onStatus(status, generation);
        } catch (Throwable error) {
            Log.e(TAG, "GNSS status callback failed", error);
        }
    }

    private void register(final long generation) {
        manager = (LocationManager) context.getSystemService(Context.LOCATION_SERVICE);
        if (manager == null || !manager.getAllProviders().contains(LocationManager.GPS_PROVIDER)) {
            status("GNSS unavailable on this device", generation);
            return;
        }
        locationListener = new LocationListener() {
            @Override public void onLocationChanged(Location location) {
                if (requestedGeneration != generation || callback == null) {
                    return;
                }
                try {
                    double ageSeconds = (SystemClock.elapsedRealtimeNanos()
                            - location.getElapsedRealtimeNanos()) / 1000000000.0;
                    callback.onLocation(location.getLongitude(), location.getLatitude(),
                            location.getTime(), ageSeconds, generation);
                } catch (Throwable error) {
                    Log.e(TAG, "GNSS location callback failed", error);
                }
            }

            @Override public void onProviderDisabled(String provider) {
                status("Location services disabled", generation);
            }

            @Override public void onProviderEnabled(String provider) {
                status("Waiting for GNSS fix", generation);
            }

            @Override public void onStatusChanged(String provider, int status, Bundle extras) {
                // Legacy provider status is not the NMEA GGA fix-quality code.
            }
        };
        nmeaListener = new OnNmeaMessageListener() {
            @Override public void onNmeaMessage(String message, long timestamp) {
                if (requestedGeneration != generation || callback == null || message == null) {
                    return;
                }
                try {
                    callback.onNmea(message, timestamp, generation);
                } catch (Throwable error) {
                    Log.e(TAG, "GNSS NMEA callback failed", error);
                }
            }
        };
        // Do not seed from getLastKnownLocation: records need a current fix.
        manager.requestLocationUpdates(LocationManager.GPS_PROVIDER, 1000L, 0.0f,
                locationListener, Looper.getMainLooper());
        try {
            manager.addNmeaListener(nmeaListener, handler);
        } catch (SecurityException error) {
            // Permission loss invalidates coordinates as well as GGA quality.
            throw error;
        } catch (RuntimeException error) {
            // Some devices expose GPS locations without working NMEA support.
            // Retain the coordinates and leave the GGA quality unknown.
            Log.w(TAG, "GNSS NMEA unavailable; keeping GPS location updates", error);
        }
        status(manager.isProviderEnabled(LocationManager.GPS_PROVIDER)
                ? "Waiting for GNSS fix" : "Location services disabled", generation);
    }

    private void unregister() {
        if (manager != null) {
            try {
                if (locationListener != null) {
                    manager.removeUpdates(locationListener);
                }
            } catch (RuntimeException error) {
                Log.w(TAG, "Could not remove GNSS location listener", error);
            }
            try {
                if (nmeaListener != null) {
                    manager.removeNmeaListener(nmeaListener);
                }
            } catch (RuntimeException error) {
                Log.w(TAG, "Could not remove GNSS NMEA listener", error);
            }
        }
        locationListener = null;
        nmeaListener = null;
    }
}
