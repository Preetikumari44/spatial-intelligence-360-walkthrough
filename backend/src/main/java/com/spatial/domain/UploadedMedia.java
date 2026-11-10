package com.spatial.domain;

import jakarta.persistence.*;
import java.time.Instant;
import java.util.UUID;
import lombok.Getter;
import lombok.Setter;

@Entity
@Table(name = "uploaded_media")
@Getter @Setter
public class UploadedMedia {
    @Id @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;
    private UUID projectId;
    private String kind;
    private String originalName;
    private String contentType;
    private long sizeBytes;
    private String storagePath;
    private Integer width;
    private Integer height;
    private Double durationSec;
    private Double fps;
    @Column(name = "is360")
    private boolean is360;
    private Instant createdAt = Instant.now();
}
