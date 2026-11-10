package com.spatial.service;

public class AiException extends RuntimeException {
    private final int upstreamStatus;

    public AiException(int upstreamStatus, String message) {
        super(message);
        this.upstreamStatus = upstreamStatus;
    }

    public int getUpstreamStatus() {
        return upstreamStatus;
    }

    public boolean isClientError() {
        return upstreamStatus >= 400 && upstreamStatus < 500;
    }
}
