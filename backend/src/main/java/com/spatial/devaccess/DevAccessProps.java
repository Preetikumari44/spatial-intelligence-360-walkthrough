package com.spatial.devaccess;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Local-development access switch. Disabled unless DEV_ACCESS=true is set in the environment.
 * See docs/DEV_ACCESS.md. Never enable this on a server that anyone but you can reach.
 *
 * @param enabled   master switch (default false)
 * @param userEmail optional: e-mail of an EXISTING user the bypass should act as; blank = the oldest existing user
 */
@ConfigurationProperties(prefix = "app.dev-access")
public record DevAccessProps(boolean enabled, String userEmail) {
}
