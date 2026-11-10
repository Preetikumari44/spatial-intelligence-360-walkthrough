package com.spatial.web;

import com.spatial.domain.User;
import com.spatial.domain.UserRepository;
import com.spatial.security.AuthUser;
import com.spatial.security.JwtService;
import com.spatial.web.Dtos.AuthResponse;
import com.spatial.web.Dtos.LoginRequest;
import com.spatial.web.Dtos.RegisterRequest;
import com.spatial.web.Dtos.UserProfile;
import jakarta.validation.Valid;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/**
 * Email and password authentication. Passwords are stored only as BCrypt hashes in the existing users table;
 * tokens come from the existing JwtService. 400 = invalid input, 401 = wrong credentials or no/invalid token,
 * 409 = e-mail already registered.
 */
@RestController
@RequestMapping("/api/auth")
public class AuthController {
    private final UserRepository users;
    private final PasswordEncoder encoder;
    private final JwtService jwt;

    public AuthController(UserRepository users, PasswordEncoder encoder, JwtService jwt) {
        this.users = users;
        this.encoder = encoder;
        this.jwt = jwt;
    }

    @PostMapping("/register")
    @ResponseStatus(HttpStatus.CREATED)
    public AuthResponse register(@Valid @RequestBody RegisterRequest req) {
        String email = req.email().trim().toLowerCase();
        if (users.findByEmailIgnoreCase(email).isPresent()) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "An account with this email already exists");
        }
        User u = new User();
        u.setEmail(email);
        u.setPasswordHash(encoder.encode(req.password()));
        u.setDisplayName(req.displayName() == null || req.displayName().isBlank() ? email : req.displayName().trim());
        try {
            users.saveAndFlush(u);
        } catch (DataIntegrityViolationException e) { // two sign-ups racing on the unique email index
            throw new ResponseStatusException(HttpStatus.CONFLICT, "An account with this email already exists");
        }
        return toResponse(u);
    }

    @PostMapping("/login")
    public AuthResponse login(@Valid @RequestBody LoginRequest req) {
        User u = users.findByEmailIgnoreCase(req.email().trim())
                .filter(x -> encoder.matches(req.password(), x.getPasswordHash()))
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid email or password"));
        return toResponse(u);
    }

    /** The signed-in user, from the Bearer token. Used by the frontend to validate a stored session. */
    @GetMapping("/me")
    public UserProfile me() {
        Authentication a = SecurityContextHolder.getContext().getAuthentication();
        if (a == null || !(a.getPrincipal() instanceof AuthUser au)) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Not signed in");
        }
        User u = users.findById(au.id()).orElseThrow(() -> new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Account no longer exists"));
        return new UserProfile(u.getId(), u.getEmail(), u.getDisplayName(), u.getRole());
    }

    private AuthResponse toResponse(User u) {
        return new AuthResponse(jwt.issue(u.getId(), u.getEmail(), u.getRole()), u.getId(), u.getEmail(), u.getDisplayName(), u.getRole());
    }
}
