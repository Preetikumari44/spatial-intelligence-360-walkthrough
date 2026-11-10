package com.spatial.security;

import java.util.UUID;

public record AuthUser(UUID id, String email, String role) {
    public boolean isAdmin() {
        return "ADMIN".equals(role);
    }
}
