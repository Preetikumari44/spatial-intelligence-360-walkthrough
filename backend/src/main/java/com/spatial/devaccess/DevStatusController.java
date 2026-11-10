package com.spatial.devaccess;

import com.fasterxml.jackson.databind.JsonNode;
import com.spatial.service.AiClient;
import jakarta.servlet.http.HttpServletRequest;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.function.Supplier;
import javax.sql.DataSource;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * GET /api/dev/status: live connection status of the three services, measured by this backend with real calls
 * (a SQL query against PostgreSQL, GET /health on the FastAPI service). Nothing here is simulated.
 *
 * When development access is off, or the caller is not local, the answer is only {"devAccess":{"enabled":false}}
 * so a production deployment discloses nothing about its infrastructure.
 */
@RestController
@RequestMapping("/api/dev")
public class DevStatusController {
    private static final long TIMEOUT_MS = 5000;
    private static final ExecutorService POOL = Executors.newVirtualThreadPerTaskExecutor();

    private final DevAccessService dev;
    private final DataSource dataSource;
    private final AiClient ai;

    public DevStatusController(DevAccessService dev, DataSource dataSource, AiClient ai) {
        this.dev = dev;
        this.dataSource = dataSource;
        this.ai = ai;
    }

    @GetMapping("/status")
    public Map<String, Object> status(HttpServletRequest req) {
        Map<String, Object> out = new LinkedHashMap<>();
        if (!dev.enabled() || !dev.isLocalRequest(req)) {
            out.put("devAccess", Map.of("enabled", false));
            return out;
        }
        var pg = CompletableFuture.supplyAsync(() -> timed(this::checkPostgres), POOL);
        var py = CompletableFuture.supplyAsync(() -> timed(this::checkPython), POOL);
        var user = dev.resolveUser();

        Map<String, Object> access = new LinkedHashMap<>();
        access.put("enabled", true);
        access.put("available", user.available());
        access.put("user", user.available() ? Map.of("email", user.user().email(), "role", user.user().role()) : null);
        access.put("message", user.message());

        Map<String, Object> services = new LinkedHashMap<>();
        services.put("java", Map.of("status", "UP", "detail", "Spring Boot, Java " + System.getProperty("java.version"), "latencyMs", 0));
        services.put("postgres", await(pg, "PostgreSQL did not answer within " + TIMEOUT_MS / 1000 + " s"));
        services.put("python", await(py, "AI service did not answer within " + TIMEOUT_MS / 1000 + " s"));

        out.put("devAccess", access);
        out.put("services", services);
        out.put("checkedAt", Instant.now().toString());
        return out;
    }

    private Map<String, Object> await(CompletableFuture<Map<String, Object>> f, String timeoutMessage) {
        try {
            return f.get(TIMEOUT_MS, TimeUnit.MILLISECONDS);
        } catch (java.util.concurrent.TimeoutException e) {
            f.cancel(true);
            return down(timeoutMessage);
        } catch (Exception e) {
            return down(String.valueOf(e.getMessage()));
        }
    }

    private Map<String, Object> checkPostgres() {
        try (Connection c = dataSource.getConnection(); Statement s = c.createStatement()) {
            s.setQueryTimeout(3);
            try (ResultSet rs = s.executeQuery("select current_setting('server_version'), (select count(*) from users)")) {
                rs.next();
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("status", "UP");
                m.put("detail", "PostgreSQL " + rs.getString(1) + ", database '" + c.getCatalog() + "'");
                m.put("users", rs.getLong(2));
                return m;
            }
        } catch (Exception e) {
            return down("PostgreSQL query failed: " + rootMessage(e));
        }
    }

    private Map<String, Object> checkPython() {
        try {
            JsonNode body = ai.get("/health");
            boolean ok = body != null && "ok".equals(body.path("status").asText());
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("status", ok ? "UP" : "DOWN");
            m.put("detail", ok ? "FastAPI answered GET /health" : "FastAPI answered, but /health did not report ok");
            if (body != null && body.has("capabilities")) {
                m.put("capabilities", body.get("capabilities"));
            }
            return m;
        } catch (Exception e) {
            return down(rootMessage(e));
        }
    }

    private Map<String, Object> timed(Supplier<Map<String, Object>> check) {
        long t0 = System.nanoTime();
        Map<String, Object> m = new LinkedHashMap<>(check.get());
        m.put("latencyMs", (System.nanoTime() - t0) / 1_000_000);
        return m;
    }

    private static Map<String, Object> down(String why) {
        return Map.of("status", "DOWN", "detail", why);
    }

    private static String rootMessage(Throwable t) {
        Throwable r = t;
        while (r.getCause() != null && r.getCause() != r) {
            r = r.getCause();
        }
        return r.getMessage() != null ? r.getMessage() : r.getClass().getSimpleName();
    }
}
