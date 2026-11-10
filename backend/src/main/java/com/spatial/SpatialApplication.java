package com.spatial;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

@SpringBootApplication
@ConfigurationPropertiesScan
public class SpatialApplication {
    public static void main(String[] args) {
        SpringApplication.run(SpatialApplication.class, args);
    }
}
