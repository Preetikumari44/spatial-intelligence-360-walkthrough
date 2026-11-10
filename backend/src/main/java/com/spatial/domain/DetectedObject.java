package com.spatial.domain;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.persistence.*;
import java.util.UUID;
import lombok.Getter;
import lombok.Setter;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

@Entity
@Table(name = "detected_objects")
@Getter @Setter
public class DetectedObject {
    @Id @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;
    private UUID projectId;
    private UUID mediaId;
    private UUID jobId;
    private String label;
    private String originalLabel;
    private Double confidence;
    @JdbcTypeCode(SqlTypes.JSON)
    private JsonNode bbox;
    @JdbcTypeCode(SqlTypes.JSON)
    private JsonNode polygon;
    private boolean edited;
}
