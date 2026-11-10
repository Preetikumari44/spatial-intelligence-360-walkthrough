package com.spatial.web;

import com.spatial.domain.UserRepository;
import java.util.List;
import java.util.Map;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/admin")
public class AdminController {
    private final UserRepository users;

    public AdminController(UserRepository users) {
        this.users = users;
    }

    @GetMapping("/users")
    @PreAuthorize("hasRole('ADMIN')")
    public List<Map<String, Object>> list() {
        return users.findAll().stream()
                .map(u -> Map.<String, Object>of("id", u.getId(), "email", u.getEmail(), "role", u.getRole(), "createdAt", u.getCreatedAt()))
                .toList();
    }
}
