package com.spatial.domain;

import java.time.Instant;
import java.util.Collection;
import java.util.List;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.transaction.annotation.Transactional;

/**
 * Job state is changed with targeted UPDATE statements, not by saving a whole entity. The worker thread and the progress
 * poller touch the same row at the same time; whole-entity saves would let a stale copy overwrite a newer status.
 */
public interface ProcessingJobRepository extends JpaRepository<ProcessingJob, UUID> {
    List<ProcessingJob> findByProjectIdOrderByCreatedAtDesc(UUID projectId);

    @Transactional
    @Modifying
    @Query("update ProcessingJob j set j.status = :status, j.message = :message, j.progress = :progress where j.id = :id")
    int updateStage(@Param("id") UUID id, @Param("status") JobStatus status, @Param("message") String message, @Param("progress") int progress);

    /** Progress ticks never touch a job that has already finished, so a late tick cannot resurrect it. */
    @Transactional
    @Modifying
    @Query("update ProcessingJob j set j.progress = :progress, j.message = :message where j.id = :id and j.status not in :terminal")
    int tick(@Param("id") UUID id, @Param("progress") int progress, @Param("message") String message, @Param("terminal") Collection<JobStatus> terminal);

    @Transactional
    @Modifying
    @Query("update ProcessingJob j set j.startedAt = :at, j.finishedAt = null, j.error = null, j.attempts = :attempts, j.progress = 0 where j.id = :id")
    int markStarted(@Param("id") UUID id, @Param("attempts") int attempts, @Param("at") Instant at);

    @Transactional
    @Modifying
    @Query("update ProcessingJob j set j.status = :status, j.message = :message, j.error = :error, j.progress = :progress, j.finishedAt = :at where j.id = :id")
    int finish(@Param("id") UUID id, @Param("status") JobStatus status, @Param("message") String message, @Param("error") String error,
               @Param("progress") int progress, @Param("at") Instant at);

    @Transactional
    @Modifying
    @Query("update ProcessingJob j set j.cancelRequested = true where j.id = :id")
    int requestCancel(@Param("id") UUID id);

    /** Back to the queue for a retry: clears the cancel flag, the error and the progress. */
    @Transactional
    @Modifying
    @Query("update ProcessingJob j set j.status = :status, j.message = :message, j.error = null, j.progress = 0, j.cancelRequested = false, j.finishedAt = null where j.id = :id")
    int requeue(@Param("id") UUID id, @Param("status") JobStatus status, @Param("message") String message);
}
