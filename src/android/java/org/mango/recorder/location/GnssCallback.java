package org.mango.recorder.location;

/** Only primitive values and strings cross the JNI callback boundary. */
public interface GnssCallback {
    void onLocation(double longitude, double latitude, long fixTimeMillis,
                    double ageSeconds, long generation);
    void onNmea(String sentence, long fixTimeMillis, long generation);
    void onStatus(String status, long generation);
}
