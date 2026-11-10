package com.spatial.domain;

public enum JobStatus {
    UPLOADED, QUEUED, PROCESSING, RECONSTRUCTING, CALIBRATING, GENERATING_TOUR,
    // added for the Open3D / Gaussian Splatting stages; older clients simply show them as text
    GENERATING_MODEL, TRAINING_SPLAT,
    COMPLETED, FAILED, CANCELLED;

    public boolean isTerminal() {
        return this == COMPLETED || this == FAILED || this == CANCELLED;
    }
}
