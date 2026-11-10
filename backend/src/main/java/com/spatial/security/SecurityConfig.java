
package com.spatial.security;

import com.spatial.config.AppProps;
import com.spatial.devaccess.DevAccessFilter;
import com.spatial.devaccess.DevAccessService;

import java.util.List;

import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.HttpStatusEntryPoint;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;

@Configuration
@EnableMethodSecurity
public class SecurityConfig {

    @Bean
    SecurityFilterChain chain(
            HttpSecurity http,
            JwtFilter jwtFilter,
            @Qualifier("corsSource") CorsConfigurationSource cors,
            DevAccessService devAccess
    ) throws Exception {

        http.csrf(c -> c.disable())
                .cors(c -> c.configurationSource(cors))
                .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .exceptionHandling(e -> e.authenticationEntryPoint(
                        new HttpStatusEntryPoint(HttpStatus.UNAUTHORIZED)))
                .authorizeHttpRequests(a -> a
                        .requestMatchers(
                                "/api/auth/**",
                                "/api/dev/status",
                                "/actuator/health",
                                "/v3/api-docs/**",
                                "/swagger-ui/**",
                                "/swagger-ui.html"
                        ).permitAll()
                        .requestMatchers(HttpMethod.OPTIONS, "/**").permitAll()
                        .anyRequest().authenticated())
                .addFilterBefore(jwtFilter, UsernamePasswordAuthenticationFilter.class);

        // Development access is enabled only when DEV_ACCESS=true.
        if (devAccess.enabled()) {
            http.addFilterAfter(
                    new DevAccessFilter(devAccess),
                    JwtFilter.class
            );
        }

        return http.build();
    }

    @Bean
    PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    /**
     * Browser origins allowed to call the API.
     */
    static List<String> allowedOrigins(String configured) {

        java.util.LinkedHashSet<String> out = new java.util.LinkedHashSet<>();

        for (String raw : (configured == null ? "" : configured).split(",")) {

            String o = raw.trim();

            while (o.endsWith("/")) {
                o = o.substring(0, o.length() - 1);
            }

            if (o.isEmpty()) {
                continue;
            }

            out.add(o);

            if (o.contains("//localhost:")) {
                out.add(o.replace("//localhost:", "//127.0.0.1:"));
            }

            if (o.contains("//127.0.0.1:")) {
                out.add(o.replace("//127.0.0.1:", "//localhost:"));
            }
        }

        if (out.isEmpty()) {
            out.addAll(List.of(
                    "http://localhost:3000",
                    "http://127.0.0.1:3000"
            ));
        }

        return List.copyOf(out);
    }

    @Bean
    CorsConfigurationSource corsSource(AppProps props) {

        CorsConfiguration cfg = new CorsConfiguration();

        cfg.setAllowedOrigins(allowedOrigins(props.corsOrigins()));
        cfg.setAllowedMethods(List.of(
                "GET", "HEAD", "POST", "PUT",
                "PATCH", "DELETE", "OPTIONS"
        ));
        cfg.setAllowedHeaders(List.of("*"));
        cfg.setMaxAge(3600L);

        UrlBasedCorsConfigurationSource src =
                new UrlBasedCorsConfigurationSource();

        src.registerCorsConfiguration("/**", cfg);

        return src;
    }
}
