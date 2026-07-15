package org.mango.recorder.speech;

import android.os.Bundle;
import android.speech.RecognitionListener;
import android.speech.SpeechRecognizer;
import android.util.Log;

import java.util.ArrayList;

/**
 * Keeps Android Bundle and ArrayList instances on the Java side. Only plain
 * strings cross the PyJNIus boundary, preventing callback conversion crashes.
 */
public final class SpeechRecognitionListener implements RecognitionListener {
    private static final String TAG = "MangoSpeechListener";
    private final SpeechCallback callback;

    public SpeechRecognitionListener(SpeechCallback callback) {
        this.callback = callback;
    }

    private void emit(String eventName, String value) {
        if (callback == null) {
            return;
        }
        try {
            callback.onSpeechEvent(eventName, value == null ? "" : value);
        } catch (Throwable error) {
            // A callback failure must not terminate the Android activity.
            Log.e(TAG, "Speech callback failed", error);
        }
    }

    private String firstResult(Bundle bundle) {
        if (bundle == null) {
            return "";
        }
        ArrayList<String> matches = bundle.getStringArrayList(
                SpeechRecognizer.RESULTS_RECOGNITION
        );
        if (matches == null || matches.isEmpty() || matches.get(0) == null) {
            return "";
        }
        return matches.get(0);
    }

    @Override
    public void onReadyForSpeech(Bundle params) {
        emit("ready", "");
    }

    @Override
    public void onBeginningOfSpeech() {
        // No UI update is needed for this high-frequency lifecycle event.
    }

    @Override
    public void onRmsChanged(float rmsdB) {
        // Avoid sending frequent audio-level callbacks through PyJNIus.
    }

    @Override
    public void onBufferReceived(byte[] buffer) {
        // Raw audio is intentionally not passed to Python.
    }

    @Override
    public void onEndOfSpeech() {
        emit("end", "");
    }

    @Override
    public void onError(int error) {
        emit("error", Integer.toString(error));
    }

    @Override
    public void onResults(Bundle results) {
        emit("results", firstResult(results));
    }

    @Override
    public void onPartialResults(Bundle partialResults) {
        emit("partial", firstResult(partialResults));
    }

    @Override
    public void onEvent(int eventType, Bundle params) {
        // Reserved by Android for service-specific events.
    }
}
