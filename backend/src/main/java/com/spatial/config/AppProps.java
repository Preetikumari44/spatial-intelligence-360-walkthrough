package com.spatial.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "app")
public record AppProps(String storageRoot, String aiUrl, String jwtSecret, long jwtTtlMinutes, String corsOrigins) {
}
