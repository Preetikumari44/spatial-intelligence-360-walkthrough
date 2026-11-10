package com.spatial.web;

import com.spatial.domain.MeasurementRecord;
import com.spatial.domain.MeasurementRecordRepository;
import com.spatial.security.AuthUser;
import com.spatial.service.AccessService;
import com.spatial.service.MeasurementService;
import com.spatial.web.Dtos.ImageCalibration;
import com.spatial.web.Dtos.MeasurementPatch;
import com.spatial.web.Dtos.VideoCalibration;
import jakarta.validation.Valid;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api")
public class MeasurementController {
    private final MeasurementService service;
    private final MeasurementRecordRepository records;
    private final AccessService access;

    public MeasurementController(MeasurementService service, MeasurementRecordRepository records, AccessService access) {
        this.service = service;
        this.records = records;
        this.access = access;
    }

    @GetMapping("/projects/{id}/measurements")
    public Map<String, Object> list(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id,
                                    @RequestParam(defaultValue = "false") boolean history) {
        access.requireProject(id, user);
        List<MeasurementRecord> all = records.findByProjectIdOrderByCreatedAtAsc(id);
        return Map.of(
                "records", history ? all : MeasurementService.current(all),
                "reconstruction", service.reconstructionSummary(id));
    }

    @PatchMapping("/measurements/{id}")
    public MeasurementRecord patch(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id, @Valid @RequestBody MeasurementPatch req) {
        MeasurementRecord r = records.findById(id).orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Measurement not found"));
        access.requireProject(r.getProjectId(), user);
        return service.patch(id, r.getProjectId(), req);
    }

    @PostMapping("/projects/{id}/calibration/image")
    public List<MeasurementRecord> calibrateImage(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id,
                                                  @Valid @RequestBody ImageCalibration req) {
        access.requireProject(id, user);
        return service.calibrateImage(id, req);
    }

    @PostMapping("/projects/{id}/calibration/video")
    public Map<String, Object> calibrateVideo(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id,
                                              @Valid @RequestBody VideoCalibration req) {
        access.requireProject(id, user);
        return service.calibrateVideo(id, req, null);
    }
}
