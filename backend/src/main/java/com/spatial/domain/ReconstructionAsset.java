package com.spatial.domain;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.persistence.*;
import java.time.Instant;
import java.util.UUID;
import lombok.Getter;
import lombok.Setter;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

@Entity
@Table(name = "reconstruction_assets")
@Getter @Setter
public class ReconstructionAsset {
    public static final String TOUR_MANIFEST = "TOUR_MANIFEST";
    public static final String POINT_PREVIEW = "POINT_PREVIEW";
    public static final String SCALE = "SCALE";
    /** work/report.json: per-stage status, device used and the list of generated files. */
    public static final String RECON_REPORT = "RECON_REPORT";

    @Id @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;
    private UUID projectId;
    private UUID jobId;
    private String assetType;
    private String storagePath;
    @JdbcTypeCode(SqlTypes.JSON)
    private JsonNode metadata;
    private Instant createdAt = Instant.now();
}
