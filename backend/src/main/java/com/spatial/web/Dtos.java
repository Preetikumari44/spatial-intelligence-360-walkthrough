package com.spatial.web;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;
import java.util.UUID;

public final class Dtos {
    private Dtos() {
    }

    public record RegisterRequest(@Email(message = "Enter a valid email address") @NotBlank(message = "Email is required") @Size(max = 255) String email,
                                  @NotBlank(message = "Password is required") @Size(min = 8, max = 72, message = "Password must be 8 to 72 characters") String password,
                                  @Size(max = 100) String displayName) {
    }

    public record LoginRequest(@NotBlank String email, @NotBlank String password) {
    }

    public record AuthResponse(String token, UUID userId, String email, String displayName, String role) {
    }

    public record UserProfile(UUID userId, String email, String displayName, String role) {
    }

    public record ProjectRequest(@NotBlank @Size(max = 150) String name, @Size(max = 50) String propertyType) {
    }

    public record JobRequest(@NotNull UUID projectId, @NotNull UUID mediaId) {
    }

    public record LabelRequest(@NotBlank @Size(max = 100) String label) {
    }

    public record MeasurementPatch(@NotNull @Positive Double valueMm, @Size(max = 300) String note) {
    }

    public record ImageCalibration(@NotNull UUID referenceObjectId, @NotNull @Positive Double realWidthMm) {
    }

    public record VideoCalibration(@NotNull UUID nodeAId, @NotNull UUID nodeBId, @NotNull @Positive Double realDistanceMm) {
    }

    public record RoomRequest(@NotBlank @Size(max = 100) String name, @Size(max = 30) String kind) {
    }

    public record NodeRoomRequest(UUID roomId) {
    }
}
