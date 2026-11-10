package com.spatial.web;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.spatial.domain.*;
import com.spatial.security.AuthUser;
import com.spatial.service.AccessService;
import com.spatial.service.MeasurementService;
import com.spatial.service.StorageService;
import com.spatial.web.Dtos.LabelRequest;
import com.spatial.web.Dtos.NodeRoomRequest;
import jakarta.validation.Valid;
import java.io.IOException;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

/** A project has at most one tour, so the tour id used in /api/tours/{id} is the project id. */
@RestController
@RequestMapping("/api")
public class TourController {
    private static final Logger log = LoggerFactory.getLogger(TourController.class);

    private final NavigationNodeRepository nodes;
    private final NavigationConnectionRepository connections;
    private final AccessService access;
    private final MeasurementService measurements;
    private final RoomRepository rooms;
    private final ReconstructionAssetRepository assets;
    private final ProcessingJobRepository jobs;
    private final StorageService storage;
    private final ObjectMapper mapper;

    public TourController(NavigationNodeRepository nodes, NavigationConnectionRepository connections,
                          AccessService access, MeasurementService measurements, RoomRepository rooms,
                          ReconstructionAssetRepository assets, ProcessingJobRepository jobs,
                          StorageService storage, ObjectMapper mapper) {
        this.rooms = rooms;
        this.nodes = nodes;
        this.connections = connections;
        this.access = access;
        this.measurements = measurements;
        this.assets = assets;
        this.jobs = jobs;
        this.storage = storage;
        this.mapper = mapper;
    }

    @GetMapping("/projects/{id}/tour")
    public Map<String, Object> tour(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id) {
        access.requireProject(id, user);
        return build(id, true);
    }

    @GetMapping("/tours/{id}/navigation")
    public Map<String, Object> navigation(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id) {
        access.requireProject(id, user);
        return build(id, false);
    }

    /** Labels are how rooms get named: automatic room segmentation is not implemented. */
    @PatchMapping("/nodes/{id}")
    public NavigationNode relabel(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id, @Valid @RequestBody LabelRequest req) {
        NavigationNode n = nodes.findById(id).orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Viewpoint not found"));
        access.requireProject(n.getProjectId(), user);
        n.setLabel(req.label().trim());
        return nodes.save(n);
    }

    /** Assign a viewpoint to a room, or clear the assignment with roomId = null. */
    @PutMapping("/nodes/{id}/room")
    public NavigationNode assignRoom(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id, @RequestBody NodeRoomRequest req) {
        NavigationNode n = nodes.findById(id).orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Viewpoint not found"));
        access.requireProject(n.getProjectId(), user);
        if (req.roomId() != null) {
            Room r = rooms.findById(req.roomId()).orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Room not found"));
            if (!r.getProjectId().equals(n.getProjectId())) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Room belongs to another project");
        }
        n.setRoomId(req.roomId());
        return nodes.save(n);
    }

    /** Manual correction: remove a link that is not a real traversable doorway. */
    @DeleteMapping("/connections/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void removeConnection(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id) {
        NavigationConnection c = connections.findById(id).orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Connection not found"));
        access.requireProject(c.getProjectId(), user);
        connections.delete(c);
    }

    private Map<String, Object> build(UUID projectId, boolean withManifest) {
        List<NavigationNode> ns = nodes.findByProjectIdOrderBySeq(projectId);
        Optional<ProcessingJob> tourJob = latestTourJob(projectId);
        tourJob.ifPresent(job -> fillMissingViewpointTimes(projectId, job, ns));
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("available", !ns.isEmpty());
        out.put("nodes", ns);
        out.put("connections", connections.findByProjectId(projectId));
        out.put("rooms", rooms.findByProjectIdOrderByCreatedAt(projectId));
        if (withManifest) {
            out.put("manifest", measurements.manifest(projectId).orElse(null));
            out.put("reconstruction", measurements.reconstructionSummary(projectId));
            out.put("sourceVideoId", tourJob.map(ProcessingJob::getMediaId).orElse(null));
        }
        return out;
    }

    private Optional<ProcessingJob> latestTourJob(UUID projectId) {
        return assets.findFirstByProjectIdAndAssetTypeOrderByCreatedAtDesc(projectId, ReconstructionAsset.TOUR_MANIFEST)
                .map(ReconstructionAsset::getJobId)
                .filter(java.util.Objects::nonNull)
                .flatMap(jobs::findById)
                .filter(job -> projectId.equals(job.getProjectId()) && "VIDEO_RECONSTRUCTION".equals(job.getType()));
    }

    private void fillMissingViewpointTimes(UUID projectId, ProcessingJob job, List<NavigationNode> viewpoints) {
        if (viewpoints.isEmpty() || viewpoints.stream().allMatch(node -> node.getTimeSec() != null)) {
            return;
        }

        String frameIndex = "projects/" + projectId + "/jobs/" + job.getId() + "/frames/frames.json";
        var indexPath = storage.resolve(frameIndex);
        if (!Files.isRegularFile(indexPath)) {
            log.warn("Frame index is missing for project {} tour job {}; viewpoint timestamps remain unavailable",
                    projectId, job.getId());
            return;
        }

        JsonNode frameEntries;
        try {
            frameEntries = mapper.readTree(Files.readString(indexPath)).path("frames");
        } catch (IOException e) {
            log.warn("Could not read frame index for project {} tour job {}; viewpoint timestamps remain unavailable",
                    projectId, job.getId(), e);
            return;
        }
        if (!frameEntries.isArray()) {
            log.warn("Frame index has no frames array for project {} tour job {}; viewpoint timestamps remain unavailable",
                    projectId, job.getId());
            return;
        }

        Map<String, Double> timeByFrame = new HashMap<>();
        for (JsonNode frame : frameEntries) {
            JsonNode path = frame.get("file");
            JsonNode time = frame.get("t");
            if (path == null || !path.isTextual() || time == null || !time.isNumber()) {
                continue;
            }
            double seconds = time.asDouble();
            if (Double.isFinite(seconds) && seconds >= 0) {
                timeByFrame.put(path.asText(), seconds);
            }
        }

        int recovered = 0;
        for (NavigationNode node : viewpoints) {
            if (node.getTimeSec() == null) {
                Double seconds = timeByFrame.get(node.getFramePath());
                if (seconds != null) {
                    node.setTimeSec(seconds);
                    recovered++;
                }
            }
        }
        long remaining = viewpoints.stream().filter(node -> node.getTimeSec() == null).count();
        if (remaining > 0) {
            log.warn("Recovered timestamps for {} viewpoints in project {}; {} have no matching frame metadata",
                    recovered, projectId, remaining);
        }
    }
}
