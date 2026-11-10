package com.spatial.domain;

import jakarta.persistence.*;
import java.time.Instant;
import java.util.UUID;
import lombok.Getter;
import lombok.Setter;

@Entity
@Table(name = "projects")
@Getter @Setter
public class Project {
    @Id @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;
    private UUID ownerId;
    private String name;
    private String propertyType;
    private String status = "CREATED";
    private Instant createdAt = Instant.now();
}
