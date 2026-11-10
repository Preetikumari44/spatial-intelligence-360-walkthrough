package com.spatial.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.spatial.domain.*;
import java.time.Instant;
import java.util.EnumSet;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

/**
 * Runs processing jobs off the request thread. Every step is a real call to the Python AI service;
 * if that service (or a tool it needs, e.g. COLMAP) is missing, the job fails with the reason.
 */
@Service
public class ProcessingService {
    private static final Logger log = LoggerFactory.getLogger(ProcessingService.class);

    private final ProcessingJobRepository jobs;
    private final UploadedMediaRepository media;
    private final ProjectRepository projects;
    private final DetectedObjectRepository objects;
    private final MeasurementRecordRepository measurements;
    private final NavigationNodeRepository nodes;
    private final NavigationConnectionRepository connections;
    private final ReconstructionAssetRepository assets;
    private final AiClient ai;
    private final ObjectMapper mapper;
    private final StorageService storage;
    /** Reads the AI service's progress while a long stage blocks the worker thread. */
    private final ScheduledExecutorService progressPoller = Executors.newSingleThreadScheduledExecutor(r -> {
        Thread t = new Thread(r, "job-progress");
        t.setDaemon(true);
        return t;
    });

    private static class JobCancelledException extends RuntimeException {
        JobCancelledException() {
            super("Cancelled by the user");
        }
    }

    public ProcessingService(ProcessingJobRepository jobs, UploadedMediaRepository media, ProjectRepository projects,
                             DetectedObjectRepository objects, MeasurementRecordRepository measurements,
                             NavigationNodeRepository nodes, NavigationConnectionRepository connections,
                             ReconstructionAssetRepository assets, AiClient ai, ObjectMapper mapper, StorageService storage) {
        this.jobs = jobs;
        this.media = media;
        this.projects = projects;
        this.objects = objects;
        this.measurements = measurements;
        this.nodes = nodes;
        this.connections = connections;
        this.assets = assets;
        this.ai = ai;
        this.mapper = mapper;
        this.storage = storage;
    }

    @PreDestroy
    void stopPoller() {
        progressPoller.shutdownNow();
    }

    @Async("jobExecutor")
    public void run(UUID jobId) {
        ProcessingJob job = jobs.findById(jobId).orElseThrow();
        if (job.getStatus() == JobStatus.CANCELLED || job.isCancelRequested()) {
            jobs.finish(jobId, JobStatus.CANCELLED, "Cancelled before it started", null, job.getProgress(), Instant.now());
            return;
        }
        jobs.markStarted(jobId, job.getAttempts() + 1, Instant.now());
        logLine(job, "Job started (attempt " + (job.getAttempts() + 1) + ", " + job.getType() + ")");
        try {
            String done;
            if ("IMAGE_ANALYSIS".equals(job.getType())) {
                runImage(job);
                done = "Completed";
            } else {
                done = runVideo(job);
            }
            jobs.finish(jobId, JobStatus.COMPLETED, truncateMessage(done), null, 100, Instant.now());
            logLine(job, done);
        } catch (JobCancelledException e) {
            jobs.finish(jobId, JobStatus.CANCELLED, "Cancelled by the user", null, currentProgress(jobId), Instant.now());
            logLine(job, "Cancelled by the user");
        } catch (AiException e) {
            if (e.getUpstreamStatus() == 499 || isCancelRequested(jobId)) {
                jobs.finish(jobId, JobStatus.CANCELLED, "Cancelled by the user", null, currentProgress(jobId), Instant.now());
                logLine(job, "Cancelled by the user");
            } else {
                failJob(job, e);
            }
        } catch (Exception e) {
            failJob(job, e);
        }
    }

    private void failJob(ProcessingJob job, Exception e) {
        log.error("Job {} failed", job.getId(), e);
        String error = truncate(e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage());
        jobs.finish(job.getId(), JobStatus.FAILED, "Failed", error, currentProgress(job.getId()), Instant.now());
        logLine(job, "FAILED: " + error);
    }

    private boolean isCancelRequested(UUID jobId) {
        return jobs.findById(jobId).map(ProcessingJob::isCancelRequested).orElse(false);
    }

    private int currentProgress(UUID jobId) {
        return jobs.findById(jobId).map(ProcessingJob::getProgress).orElse(0);
    }

    private void runImage(ProcessingJob job) {
        UploadedMedia m = media.findById(job.getMediaId()).orElseThrow();
        step(job, JobStatus.PROCESSING, "Detecting and segmenting objects", 10);
        JsonNode res = callAi(job, "/image/analyze", Map.of("image_path", m.getStoragePath()));

        m.setWidth(res.path("image").path("width").asInt());
        m.setHeight(res.path("image").path("height").asInt());
        media.save(m);

        for (DetectedObject old : objects.findByMediaId(m.getId())) {
            measurements.deleteAll(measurements.findByObjectIdOrderByCreatedAtAsc(old.getId()));
        }
        objects.deleteByMediaId(m.getId());

        for (JsonNode o : res.path("objects")) {
            DetectedObject d = new DetectedObject();
            d.setProjectId(job.getProjectId());
            d.setMediaId(m.getId());
            d.setJobId(job.getId());
            d.setLabel(o.path("label").asText());
            d.setOriginalLabel(d.getLabel());
            d.setConfidence(o.path("confidence").asDouble());
            d.setBbox(o.get("bbox"));
            d.setPolygon(o.get("polygon"));
            d = objects.save(d);

            JsonNode dims = o.get("dimensions");
            if (dims != null && !dims.isNull()) {
                for (String kind : List.of("width", "height", "depth")) {
                    JsonNode v = dims.get(kind + "_mm");
                    if (v == null || v.isNull()) {
                        continue;
                    }
                    MeasurementRecord r = new MeasurementRecord();
                    r.setProjectId(job.getProjectId());
                    r.setObjectId(d.getId());
                    r.setKind(kind);
                    r.setValueMm(v.asDouble());
                    r.setStatus("ESTIMATED");
                    r.setConfidence(dims.hasNonNull("confidence") ? dims.get("confidence").asDouble() : null);
                    r.setSource(dims.path("method").asText("unknown"));
                    r.setNote(dims.path("note").asText(null));
                    measurements.save(r);
                }
            }
        }
        touchProject(job.getProjectId(), "IMAGE_ANALYZED");
    }

    /**
     * Returns the final job message.
     * Pipeline A (frames -> viewpoints -> navigation -> validated tour) needs no COLMAP and no 3D library; once it succeeds the walkthrough
     * is available. Pipeline B (camera poses, point cloud, mesh, Gaussians) is optional: any failure there is reported in the job
     * message and report.json, and never removes or blocks the tour.
     */
    private String runVideo(ProcessingJob job) {
        UploadedMedia m = media.findById(job.getMediaId()).orElseThrow();
        UUID pid = job.getProjectId();
        String base = "projects/" + pid + "/jobs/" + job.getId();
        boolean is360 = m.is360();
        boolean preserveExistingPoseTour = nodes.findByProjectIdOrderBySeq(pid).stream().anyMatch(NavigationNode::isHasPose);

        step(job, JobStatus.PROCESSING, "Extracting sharp, non-duplicate frames", 2);
        JsonNode frames = callAi(job, "/video/frames", Map.of("video_path", m.getStoragePath(), "out_dir", base + "/frames", "is_360", is360));

        // ---- Pipeline A: the virtual tour, from the extracted frames only ----
        step(job, JobStatus.GENERATING_TOUR, "Building viewpoints and navigation from " + frames.path("kept").asInt() + " frames", 12);
        JsonNode viewpointTour = callAi(job, "/video/viewpoints", Map.of("frames_dir", base + "/frames", "work_dir", base + "/tour", "is_360", is360));
        if (preserveExistingPoseTour) {
            logLine(job, "Generated candidate tour: " + viewpointTour.path("nodes").size() + " viewpoints, "
                    + viewpointTour.path("connections").size() + " links; preserving the existing pose-based tour until an upgraded tour is validated.");
        } else {
            replaceTour(job, pid, viewpointTour);
            touchProject(pid, "TOUR_READY");
            logLine(job, "Virtual tour ready: " + viewpointTour.path("nodes").size() + " viewpoints, "
                    + viewpointTour.path("connections").size() + " links (no 3D reconstruction was needed)");
        }

        // ---- Pipeline B: advanced 3D, optional and isolated ----
        try {
            return runAdvanced3d(job, pid, base, is360, viewpointTour, preserveExistingPoseTour);
        } catch (JobCancelledException e) {
            throw e;
        } catch (RuntimeException e) {
            String why = e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage();
            logLine(job, "Advanced 3D reconstruction did not complete: " + why);
            String result = preserveExistingPoseTour
                    ? "existing pose-based tour preserved; updated reconstruction was not saved"
                    : "virtual tour is ready; advanced 3D failed";
            return "Completed with limitations: " + result + " (" + (why.length() > 120 ? why.substring(0, 120) + "..." : why) + ")";
        }
    }

    private String runAdvanced3d(ProcessingJob job, UUID pid, String base, boolean is360, JsonNode viewpointTour,
                                 boolean preserveExistingPoseTour) {
        step(job, JobStatus.RECONSTRUCTING, "Estimating camera poses (advanced 3D)", 30);
        JsonNode recon = callAi(job, "/video/reconstruct", Map.of("frames_dir", base + "/frames", "work_dir", base + "/work", "is_360", is360));
        logLine(job, "Camera poses: " + recon.path("registered_images").asInt() + " of " + recon.path("total_images").asInt()
                + " images registered with " + recon.path("backend").asText("?") + ", " + recon.path("points").asInt() + " sparse points");

        step(job, JobStatus.CALIBRATING, "Reconstruction is in arbitrary model units; real-world scale needs a reference distance", 67);
        // a new reconstruction has new model units, so any older scale no longer applies
        assets.deleteByProjectIdAndAssetType(pid, ReconstructionAsset.SCALE);

        step(job, JobStatus.RECONSTRUCTING, "Upgrading the tour with real camera positions, hotspots and floor plan", 68);
        JsonNode poseTour = callAi(job, "/video/tour", Map.of(
                "work_dir", base + "/work", "is_360", is360, "fallback_tour", viewpointTour));
        int poseViewpoints = 0;
        for (JsonNode node : poseTour.path("nodes")) {
            JsonNode hasPose = node.path("has_pose");
            if (hasPose.isBoolean() ? hasPose.asBoolean()
                    : node.path("position").isArray() && node.path("position").size() == 3) {
                poseViewpoints++;
            }
        }
        int totalViewpoints = viewpointTour.path("nodes").size();
        if (poseTour.path("validation").path("passed").asBoolean(false)
                && totalViewpoints > 0 && poseTour.path("nodes").size() == totalViewpoints) {
            replaceTour(job, pid, poseTour);
            logLine(job, "Walkthrough upgraded with " + poseViewpoints + " pose-based viewpoints while retaining "
                    + (totalViewpoints - poseViewpoints) + " frame-only viewpoints.");
        } else {
            logLine(job, preserveExistingPoseTour
                    ? "Keeping the existing pose-based tour; the new pose graph could not be safely matched to all source frames."
                    : "Keeping the complete frame-based tour (" + totalViewpoints
                            + " viewpoints); the pose-based graph could not be safely matched to all source frames.");
        }
        // Register the report now so a later failure still leaves the advanced 3D outputs reachable.
        saveAsset(job, pid, ReconstructionAsset.RECON_REPORT, base + "/work/report.json", null);

        // Optional outputs. The AI service records each stage's real status (ok / failed / unavailable) in report.json;
        // a problem here never turns the valid camera-pose reconstruction into a failure and never hides itself.
        step(job, JobStatus.GENERATING_MODEL, "Building point cloud and mesh with Open3D", 70);
        callAi(job, "/video/model", Map.of("frames_dir", base + "/frames", "work_dir", base + "/work"));

        step(job, JobStatus.TRAINING_SPLAT, "Training Gaussian splats", 87);
        callAi(job, "/video/splat", Map.of("frames_dir", base + "/frames", "work_dir", base + "/work"));

        touchProject(pid, "RECONSTRUCTED");
        return summarise(base + "/work/report.json");
    }

    /** Replaces the project's navigation nodes, links and tour manifest with a freshly validated tour (called only after the AI service succeeded). */
    private void replaceTour(ProcessingJob job, UUID pid, JsonNode tour) {
        Map<String, NavigationNode> existingByFrame = new HashMap<>();
        Map<Double, NavigationNode> existingByTime = new HashMap<>();
        for (NavigationNode existing : nodes.findByProjectIdOrderBySeq(pid)) {
            existingByFrame.put(existing.getFramePath().replace('\\', '/'), existing);
            if (existing.getTimeSec() != null) existingByTime.put(existing.getTimeSec(), existing);
        }
        connections.deleteByProjectId(pid);
        nodes.deleteByProjectId(pid);
        assets.deleteByProjectIdAndAssetType(pid, ReconstructionAsset.TOUR_MANIFEST);
        assets.deleteByProjectIdAndAssetType(pid, ReconstructionAsset.POINT_PREVIEW);
        assets.deleteByProjectIdAndAssetType(pid, ReconstructionAsset.RECON_REPORT);

        Map<String, UUID> ids = new HashMap<>();
        for (JsonNode n : tour.path("nodes")) {
            NavigationNode nn = new NavigationNode();
            nn.setProjectId(pid);
            nn.setSeq(n.path("seq").asInt());
            nn.setLabel(n.path("label").asText());
            nn.setFramePath(n.path("frame").asText());
            nn.setPanorama(n.path("panorama").asBoolean());
            JsonNode pos = n.path("position");
            boolean hasPosition = pos.isArray() && pos.size() == 3;
            if (hasPosition) {
                for (JsonNode coordinate : pos) {
                    if (!coordinate.isNumber() || !Double.isFinite(coordinate.asDouble())) {
                        hasPosition = false;
                        break;
                    }
                }
            }
            JsonNode declaredPose = n.get("has_pose");
            boolean hasPose = hasPosition && (declaredPose == null
                    || (declaredPose.isBoolean() && declaredPose.asBoolean()));
            nn.setHasPose(hasPose);
            nn.setX(hasPose ? pos.get(0).asDouble() : 0.0);
            nn.setY(hasPose ? pos.get(1).asDouble() : 0.0);
            nn.setZ(hasPose ? pos.get(2).asDouble() : 0.0);
            nn.setHeadingRad(hasPose ? n.path("heading_rad").asDouble(0.0) : 0.0);
            nn.setTimeSec(n.path("time_sec").isNumber() ? n.path("time_sec").asDouble() : null);
            nn.setCamera(hasPose ? n.get("camera") : null);
            String sourceFrame = n.path("source_frame").asText(n.path("frame").asText()).replace('\\', '/');
            NavigationNode previous = existingByFrame.get(sourceFrame);
            if (previous == null && nn.getTimeSec() != null) previous = existingByTime.get(nn.getTimeSec());
            if (previous != null) {
                if (previous.getRoomId() != null) nn.setRoomId(previous.getRoomId());
                if (previous.getLabel() != null && !previous.getLabel().isBlank()) nn.setLabel(previous.getLabel());
            }
            ids.put(n.path("id").asText(), nodes.save(nn).getId());
        }
        for (JsonNode c : tour.path("connections")) {
            NavigationConnection nc = new NavigationConnection();
            nc.setProjectId(pid);
            nc.setFromNodeId(ids.get(c.path("from").asText()));
            nc.setToNodeId(ids.get(c.path("to").asText()));
            nc.setHotspot(c.get("hotspot"));
            nc.setDistanceUnits(c.path("distance").asDouble());
            connections.save(nc);
        }
        saveAsset(job, pid, ReconstructionAsset.TOUR_MANIFEST, tour.path("manifest_path").asText(), null);
        JsonNode points = tour.path("points_path");
        if (points.isTextual() && !points.asText().isBlank()) {
            saveAsset(job, pid, ReconstructionAsset.POINT_PREVIEW, points.asText(), null);
        }
    }

    /** "Completed" when every stage worked, otherwise a short list of what did not, taken from the AI service's own report. */
    private String summarise(String reportPath) {
        try {
            JsonNode stages = mapper.readTree(storage.readTextOrEmpty(reportPath)).path("stages");
            StringBuilder problems = new StringBuilder();
            for (String key : List.of("point_cloud", "mesh", "gaussian_splat")) {
                JsonNode st = stages.path(key);
                String status = st.path("status").asText("missing");
                if (!"ok".equals(status)) {
                    if (problems.length() > 0) {
                        problems.append("; ");
                    }
                    problems.append(key.replace('_', ' ')).append(' ').append(status);
                    String why = st.path("message").asText("");
                    if (!why.isBlank()) {
                        problems.append(" (").append(why.length() > 90 ? why.substring(0, 90) + "…" : why).append(')');
                    }
                }
            }
            return problems.length() == 0 ? "Completed" : "Completed with limitations: " + problems;
        } catch (Exception e) {
            return "Completed (report unreadable)";
        }
    }

    /** One AI call, with progress polling while it runs and an early exit if the user cancelled. */
    private JsonNode callAi(ProcessingJob job, String path, Map<String, Object> body) {
        if (isCancelRequested(job.getId())) {
            throw new JobCancelledException();
        }
        Map<String, Object> payload = new HashMap<>(body);
        payload.put("job_id", job.getId().toString());
        ScheduledFuture<?> poll = progressPoller.scheduleWithFixedDelay(() -> pollProgress(job.getId()), 1, 2, TimeUnit.SECONDS);
        try {
            return ai.post(path, payload);
        } finally {
            poll.cancel(false);
        }
    }

    private void pollProgress(UUID jobId) {
        try {
            JsonNode st = ai.get("/jobs/" + jobId + "/status");
            if (st.path("known").asBoolean(false) && st.path("progress").asInt() > 0) {
                jobs.tick(jobId, st.path("progress").asInt(), truncateMessage(st.path("message").asText("")),
                        EnumSet.of(JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED));
            }
        } catch (Exception ignored) {
            // progress is best effort; the blocking call reports the real outcome
        }
    }

    private void saveAsset(ProcessingJob job, UUID pid, String type, String path, JsonNode meta) {
        ReconstructionAsset a = new ReconstructionAsset();
        a.setProjectId(pid);
        a.setJobId(job.getId());
        a.setAssetType(type);
        a.setStoragePath(path);
        a.setMetadata(meta);
        assets.save(a);
    }

    private void touchProject(UUID id, String status) {
        projects.findById(id).ifPresent(p -> {
            p.setStatus(status);
            projects.save(p);
        });
    }

    private void step(ProcessingJob job, JobStatus status, String message, int progress) {
        if (isCancelRequested(job.getId())) {
            throw new JobCancelledException();
        }
        jobs.updateStage(job.getId(), status, truncateMessage(message), progress);
        logLine(job, status + ": " + message);
    }

    private void logLine(ProcessingJob job, String line) {
        storage.appendLine("projects/" + job.getProjectId() + "/jobs/" + job.getId() + "/job.log", Instant.now() + " " + line);
    }

    private static String truncateMessage(String s) {
        return s.length() > 480 ? s.substring(0, 480) : s;
    }

    private static String truncate(String s) {
        return s.length() > 1900 ? s.substring(0, 1900) : s;
    }

    public ObjectNode scaleMetadata(double mmPerUnit, UUID a, UUID b, double realMm, double modelDistance) {
        ObjectNode n = mapper.createObjectNode();
        n.put("mmPerUnit", mmPerUnit);
        n.put("nodeAId", a.toString());
        n.put("nodeBId", b.toString());
        n.put("realDistanceMm", realMm);
        n.put("modelDistance", modelDistance);
        return n;
    }
}
