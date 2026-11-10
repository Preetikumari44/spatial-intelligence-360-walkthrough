package com.spatial.devaccess;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.spatial.config.AppProps;
import com.spatial.domain.User;
import com.spatial.domain.UserRepository;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.mock.web.MockHttpServletRequest;

class DevAccessServiceTest {
    private static final AppProps APP = new AppProps("storage", "http://localhost:8000", "x".repeat(32), 60,
            "http://localhost:3000,http://127.0.0.1:3000");

    private final UserRepository users = mock(UserRepository.class);

    private DevAccessService service(boolean enabled, String email, MockEnvironment env) {
        return new DevAccessService(new DevAccessProps(enabled, email), env, users, APP, 8080);
    }

    private static MockHttpServletRequest request(String remote) {
        MockHttpServletRequest r = new MockHttpServletRequest();
        r.setRemoteAddr(remote);
        return r;
    }

    @Test
    void disabledByDefaultNothingIsLocal() {
        var s = service(false, "", new MockEnvironment());
        assertFalse(s.enabled());
        assertFalse(s.isLocalRequest(request("127.0.0.1")));
    }

    @Test
    void loopbackIsAcceptedRemoteIsNot() {
        var s = service(true, "", new MockEnvironment());
        assertTrue(s.isLocalRequest(request("127.0.0.1")));
        assertTrue(s.isLocalRequest(request("0:0:0:0:0:0:0:1")));
        assertFalse(s.isLocalRequest(request("192.168.1.20")));
        assertFalse(s.isLocalRequest(request("8.8.8.8")));
    }

    @Test
    void proxiedRequestsAreRejected() {
        var s = service(true, "", new MockEnvironment());
        var r = request("127.0.0.1");
        r.addHeader("X-Forwarded-For", "203.0.113.9");
        assertFalse(s.isLocalRequest(r));
    }

    @Test
    void foreignBrowserOriginIsRejected() {
        var s = service(true, "", new MockEnvironment());
        var evil = request("127.0.0.1");
        evil.addHeader("Origin", "https://evil.example");
        assertFalse(s.isLocalRequest(evil));
        var ok = request("127.0.0.1");
        ok.addHeader("Origin", "http://localhost:3000");
        assertTrue(s.isLocalRequest(ok));
    }

    @Test
    void refusesToStartInProduction() {
        var env = new MockEnvironment();
        env.setActiveProfiles("prod");
        assertThrows(IllegalStateException.class, () -> service(true, "", env).validate());
        // a disabled switch is fine in production
        service(false, "", env).validate();
    }

    @Test
    void usesOnlyExistingUsersAndNeverInventsOne() {
        when(users.findFirstByOrderByCreatedAtAsc()).thenReturn(Optional.empty());
        var none = service(true, "", new MockEnvironment()).resolveUser();
        assertFalse(none.available());

        User u = new User();
        u.setId(java.util.UUID.randomUUID());
        u.setEmail("me@example.com");
        when(users.findFirstByOrderByCreatedAtAsc()).thenReturn(Optional.of(u));
        var found = service(true, "", new MockEnvironment()).resolveUser();
        assertTrue(found.available());
        assertEquals("me@example.com", found.user().email());
    }

    @Test
    void configuredEmailMustExist() {
        when(users.findByEmailIgnoreCase("ghost@example.com")).thenReturn(Optional.empty());
        assertFalse(service(true, "ghost@example.com", new MockEnvironment()).resolveUser().available());
    }
}
