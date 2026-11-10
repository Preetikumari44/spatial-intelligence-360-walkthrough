package com.spatial.domain;

import jakarta.persistence.*;
import java.time.Instant;
import java.util.UUID;
import lombok.Getter;
import lombok.Setter;

@Entity
@Table(name = "processing_jobs")
@Getter @Setter
public class ProcessingJob {
    @Id @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;
    private UUID projectId;
    private UUID mediaId;
    private String type;
    @Enumerated(EnumType.STRING)
    private JobStatus status = JobStatus.QUEUED;
    private String message;
    private String error;
    private int attempts;
    /** 0-100, as reported by the AI service while a stage runs. */
    private int progress;
    private boolean cancelRequested;
    private Instant createdAt = Instant.now();
    private Instant startedAt;
    private Instant finishedAt;
}
