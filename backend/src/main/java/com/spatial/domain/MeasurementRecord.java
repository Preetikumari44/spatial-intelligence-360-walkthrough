package com.spatial.domain;

import jakarta.persistence.*;
import java.time.Instant;
import java.util.UUID;
import lombok.Getter;
import lombok.Setter;

@Entity
@Table(name = "measurement_records")
@Getter @Setter
public class MeasurementRecord {
    @Id @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;
    private UUID projectId;
    private UUID objectId;
    private String kind;
    private Double valueMm;
    /** ESTIMATED, CALIBRATED or VERIFIED */
    private String status;
    private Double confidence;
    private String source;
    private String note;
    private Instant createdAt = Instant.now();
}
