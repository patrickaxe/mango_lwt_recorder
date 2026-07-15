package org.mango.recorder.speech;

/** A minimal string-only bridge from Android speech callbacks to Python. */
public interface SpeechCallback {
    void onSpeechEvent(String eventName, String value);
}
