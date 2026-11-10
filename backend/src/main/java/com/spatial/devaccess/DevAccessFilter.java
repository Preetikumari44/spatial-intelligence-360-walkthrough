package com.spatial.devaccess;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.List;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Runs after JwtFilter, and only when development access is enabled (SecurityConfig adds it conditionally; it is
 * deliberately NOT a Spring bean, so it can never be registered by accident).
 *
 * A request that carries a valid token is authenticated by JwtFilter as usual and is left alone. Only requests that
 * are still unauthenticated, are local, and target /api/ (not /api/auth/) are given an existing real user.
 */
public class DevAccessFilter extends OncePerRequestFilter {
    static final String HEADER = "X-Dev-Access";

    private final DevAccessService dev;

    public DevAccessFilter(DevAccessService dev) {
        this.dev = dev;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain)
            throws ServletException, IOException {
        String uri = req.getRequestURI();
        boolean api = uri.startsWith("/api/") && !uri.startsWith("/api/auth/") && !uri.startsWith("/api/dev/");
        if (api && SecurityContextHolder.getContext().getAuthentication() == null && dev.isLocalRequest(req)) {
            var resolved = dev.resolveUser();
            if (resolved.available()) {
                var u = resolved.user();
                SecurityContextHolder.getContext().setAuthentication(
                        new UsernamePasswordAuthenticationToken(u, null, List.of(new SimpleGrantedAuthority("ROLE_" + u.role()))));
                res.setHeader(HEADER, "on");
            }
        }
        chain.doFilter(req, res);
    }
}
