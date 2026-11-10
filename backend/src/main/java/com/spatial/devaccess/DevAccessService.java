package com.spatial.devaccess;

import com.spatial.config.AppProps;
import com.spatial.domain.User;
import com.spatial.domain.UserRepository;
import com.spatial.security.AuthUser;
import jakarta.annotation.PostConstruct;
import jakarta.servlet.http.HttpServletRequest;
import java.net.InetAddress;
import java.net.UnknownHostException;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.env.Environment;
import org.springframework.core.env.Profiles;
import org.springframework.stereotype.Service;

/**
 * Decides whether a request may use the development access bypass, and which REAL user it acts as.
 *
 * The bypass never creates users, never issues or accepts a made-up token and never touches password
 * hashing or the JWT code. It only fills an empty security context with an account that already exists
 * in the database, so ownership checks and foreign keys keep working exactly as in normal operation.
 */
@Service
public class DevAccessService {
    private static final Logger log = LoggerFactory.getLogger(DevAccessService.class);
    private static final List<String> PROXY_HEADERS = List.of("X-Forwarded-For", "Forwarded", "X-Forwarded-Host", "X-Real-IP");

    /** Result of looking up the account the bypass acts as. */
    public record DevUser(AuthUser user, String message) {
        public boolean available() {
            return user != null;
        }
    }

    private final DevAccessProps props;
    private final Environment env;
    private final UserRepository users;
    private final Set<String> allowedOrigins = new HashSet<>();

    public DevAccessService(DevAccessProps props, Environment env, UserRepository users, AppProps app,
                            @Value("${server.port:8080}") int serverPort) {
        this.props = props;
        this.env = env;
        this.users = users;
        Arrays.stream(app.corsOrigins().split(",")).map(String::trim).filter(s -> !s.isEmpty()).forEach(allowedOrigins::add);
        allowedOrigins.add("http://localhost:" + serverPort);
        allowedOrigins.add("http://127.0.0.1:" + serverPort);
    }

    @PostConstruct
    void validate() {
        if (!props.enabled()) {
            return;
        }
        if (env.acceptsProfiles(Profiles.of("prod", "production", "staging"))) {
            throw new IllegalStateException("DEV_ACCESS=true is not allowed with a prod, production or staging Spring profile. "
                    + "Set DEV_ACCESS=false (or remove it) and start again.");
        }
        log.warn("""

                ==========================================================================
                  DEVELOPMENT ACCESS IS ON: authentication is bypassed for requests that
                  come from this machine. Do NOT use this on a shared or public server.
                  Set DEV_ACCESS=false and restart to switch it off. See docs/DEV_ACCESS.md
                ==========================================================================
                """);
    }

    public boolean enabled() {
        return props.enabled();
    }

    /**
     * True only for requests that come straight from this machine's loopback interface, are not relayed by a proxy,
     * and (if they carry an Origin header) come from one of the configured front-end origins. The Origin check stops
     * an unrelated web page open in the same browser from driving the API.
     */
    public boolean isLocalRequest(HttpServletRequest req) {
        if (!props.enabled()) {
            return false;
        }
        for (String h : PROXY_HEADERS) {
            if (req.getHeader(h) != null) {
                return false;
            }
        }
        try {
            if (!InetAddress.getByName(req.getRemoteAddr()).isLoopbackAddress()) {
                return false;
            }
        } catch (UnknownHostException e) {
            return false;
        }
        String origin = req.getHeader("Origin");
        return origin == null || allowedOrigins.contains(origin);
    }

    /** The existing account the bypass acts as: DEV_ACCESS_EMAIL if set, otherwise the oldest registered user. */
    public DevUser resolveUser() {
        String email = props.userEmail();
        if (email != null && !email.isBlank()) {
            Optional<User> u = users.findByEmailIgnoreCase(email.trim());
            return u.map(x -> new DevUser(toAuth(x), "Acting as " + x.getEmail() + " (DEV_ACCESS_EMAIL)"))
                    .orElseGet(() -> new DevUser(null, "DEV_ACCESS_EMAIL is set to " + email.trim()
                            + " but no such user exists. Register it once on /login, or clear DEV_ACCESS_EMAIL."));
        }
        return users.findFirstByOrderByCreatedAtAsc()
                .map(x -> new DevUser(toAuth(x), "Acting as " + x.getEmail() + " (oldest registered user)"))
                .orElseGet(() -> new DevUser(null, "No user exists in the database yet. Register one account once on /login "
                        + "(registration is unchanged); development access will then use it automatically."));
    }

    private static AuthUser toAuth(User u) {
        return new AuthUser(u.getId(), u.getEmail(), u.getRole());
    }
}
