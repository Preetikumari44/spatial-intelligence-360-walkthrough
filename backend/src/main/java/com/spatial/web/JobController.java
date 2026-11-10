package com.spatial.web;

import com.spatial.domain.*;
import com.spatial.security.AuthUser;
import com.spatial.service.AccessService;
import com.spatial.service.AiClient;
import com.spatial.service.AiException;
import com.spatial.service.ProcessingService;
import com.spatial.service.StorageService;
import java.time.Instant;
import java.util.Map;
import com.spatial.web.Dtos.JobRequest;
import jakarta.annotation.PreDestroy;
import jakarta.validation.Valid;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@RestController
@RequestMapping("/api")
public class JobController {
    private final ProcessingJobRepository jobs;
    private final UploadedMediaRepository media;
    private final AccessService access;
    private final ProcessingService processing;
    private final AiClient ai;
    private final StorageService storage;
    private final ScheduledExecutorService poller = Executors.newScheduledThreadPool(2);

    public JobController(ProcessingJobRepository jobs, UploadedMediaRepository media, AccessService access, ProcessingService processing,
                         AiClient ai, StorageService storage) {
        this.jobs = jobs;
        this.media = media;
        this.access = access;
        this.processing = processing;
        this.ai = ai;
        this.storage = storage;
    }

    @PostMapping("/ai/image-analysis")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public ProcessingJob analyzeImage(@AuthenticationPrincipal AuthUser user, @Valid @RequestBody JobRequest req) {
        return enqueue(user, req, "IMAGE", "IMAGE_ANALYSIS");
    }

    @PostMapping("/ai/video-reconstruction")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public ProcessingJob reconstructVideo(@AuthenticationPrincipal AuthUser user, @Valid @RequestBody JobRequest req) {
        return enqueue(user, req, "VIDEO", "VIDEO_RECONSTRUCTION");
    }

    @GetMapping("/jobs/{id}")
    public ProcessingJob get(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id) {
        return owned(id, user);
    }

    @GetMapping("/projects/{id}/jobs")
    public List<ProcessingJob> forProject(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id) {
        access.requireProject(id, user);
        return jobs.findByProjectIdOrderByCreatedAtDesc(id);
    }

    @PostMapping("/jobs/{id}/retry")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public ProcessingJob retry(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id) {
        ProcessingJob j = owned(id, user);
        if (j.getStatus() != JobStatus.FAILED && j.getStatus() != JobStatus.CANCELLED) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Only failed or cancelled jobs can be retried");
        }
        jobs.requeue(id, JobStatus.QUEUED, "Queued (retry)");
        processing.run(id);
        return jobs.findById(id).orElseThrow();
    }

    /**
     * Cooperative cancel: the flag is checked between stages, and the AI service stops its current loop or kills COLMAP.
     * A job still waiting in the queue is cancelled immediately.
     */
    @PostMapping("/jobs/{id}/cancel")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public ProcessingJob cancel(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id) {
        ProcessingJob j = owned(id, user);
        if (j.getStatus().isTerminal()) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "This job has already finished");
        }
        jobs.requestCancel(id);
        if (j.getStatus() == JobStatus.QUEUED) {
            jobs.finish(id, JobStatus.CANCELLED, "Cancelled before it started", null, j.getProgress(), Instant.now());
        } else {
            try {
                ai.post("/jobs/" + id + "/cancel", Map.of());
            } catch (AiException ignored) {
                // the worker also sees the flag between stages; an unreachable AI service has nothing left to stop
            }
        }
        return jobs.findById(id).orElseThrow();
    }

    /** The backend's own step log followed by the AI service's log for the same job. */
    @GetMapping(value = "/jobs/{id}/logs", produces = MediaType.TEXT_PLAIN_VALUE)
    public String logs(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id) {
        ProcessingJob j = owned(id, user);
        String dir = "projects/" + j.getProjectId() + "/jobs/" + id;
        String backend = storage.readTextOrEmpty(dir + "/job.log");
        String aiLog = storage.readTextOrEmpty(dir + "/ai.log");
        return backend + (aiLog.isEmpty() ? "" : "\n--- AI service ---\n" + aiLog);
    }

    @GetMapping(value = "/jobs/{id}/events", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter events(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id) {
        owned(id, user);
        SseEmitter emitter = new SseEmitter(30 * 60_000L);
        AtomicReference<ScheduledFuture<?>> task = new AtomicReference<>();
        Runnable stop = () -> {
            ScheduledFuture<?> f = task.get();
            if (f != null) {
                f.cancel(false);
            }
        };
        task.set(poller.scheduleWithFixedDelay(() -> {
            try {
                ProcessingJob j = jobs.findById(id).orElseThrow();
                emitter.send(SseEmitter.event().name("job").data(j, MediaType.APPLICATION_JSON));
                if (j.getStatus().isTerminal()) {
                    emitter.complete();
                    stop.run();
                }
            } catch (Exception e) {
                emitter.completeWithError(e);
                stop.run();
            }
        }, 0, 1500, TimeUnit.MILLISECONDS));
        emitter.onCompletion(stop);
        emitter.onTimeout(stop);
        return emitter;
    }

    @PreDestroy
    void shutdown() {
        poller.shutdownNow();
    }

    private ProcessingJob enqueue(AuthUser user, JobRequest req, String mediaKind, String type) {
        access.requireProject(req.projectId(), user);
        UploadedMedia m = media.findById(req.mediaId())
                .filter(x -> x.getProjectId().equals(req.projectId()))
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Media not found in this project"));
        if (!m.getKind().equals(mediaKind)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, type + " needs a " + mediaKind.toLowerCase() + " upload");
        }
        ProcessingJob j = new ProcessingJob();
        j.setProjectId(req.projectId());
        j.setMediaId(req.mediaId());
        j.setType(type);
        j.setStatus(JobStatus.QUEUED);
        j.setMessage("Queued");
        j = jobs.save(j);
        processing.run(j.getId());
        return j;
    }

    private ProcessingJob owned(UUID id, AuthUser user) {
        ProcessingJob j = jobs.findById(id).orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Job not found"));
        access.requireProject(j.getProjectId(), user);
        return j;
    }
}
