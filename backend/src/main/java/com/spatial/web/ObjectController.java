package com.spatial.web;

import com.spatial.domain.*;
import com.spatial.security.AuthUser;
import com.spatial.service.AccessService;
import com.spatial.service.MeasurementService;
import com.spatial.web.Dtos.LabelRequest;
import jakarta.validation.Valid;
import java.util.List;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api")
public class ObjectController {
    private final DetectedObjectRepository objects;
    private final MeasurementRecordRepository records;
    private final AccessService access;

    public ObjectController(DetectedObjectRepository objects, MeasurementRecordRepository records, AccessService access) {
        this.objects = objects;
        this.records = records;
        this.access = access;
    }

    @GetMapping("/projects/{id}/objects")
    public List<DetectedObject> list(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id,
                                     @RequestParam(required = false) UUID mediaId) {
        access.requireProject(id, user);
        return mediaId == null ? objects.findByProjectId(id) : objects.findByMediaId(mediaId);
    }

    @PatchMapping("/objects/{id}")
    public DetectedObject relabel(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id, @Valid @RequestBody LabelRequest req) {
        DetectedObject o = owned(id, user);
        o.setLabel(req.label().trim());
        o.setEdited(true);
        return objects.save(o);
    }

    /** Current values plus the full history for one object. */
    @GetMapping("/objects/{id}/measurements")
    public java.util.Map<String, Object> measurements(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id) {
        owned(id, user);
        List<MeasurementRecord> history = records.findByObjectIdOrderByCreatedAtAsc(id);
        return java.util.Map.of("current", MeasurementService.current(history), "history", history);
    }

    private DetectedObject owned(UUID id, AuthUser user) {
        DetectedObject o = objects.findById(id).orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Object not found"));
        access.requireProject(o.getProjectId(), user);
        return o;
    }
}
