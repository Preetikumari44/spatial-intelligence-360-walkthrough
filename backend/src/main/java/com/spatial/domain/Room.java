package com.spatial.domain;

import jakarta.persistence.*;
import java.time.Instant;
import java.util.UUID;
import lombok.Getter;
import lombok.Setter;

@Entity
@Table(name = "rooms")
@Getter @Setter
public class Room {
    @Id @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;
    private UUID projectId;
    private String name;
    private String kind = "OTHER";
    private String source = "MANUAL";
    private Instant createdAt = Instant.now();
}
