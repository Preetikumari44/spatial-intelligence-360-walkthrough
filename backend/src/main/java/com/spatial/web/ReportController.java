package com.spatial.web;

import com.spatial.domain.*;
import com.spatial.security.AuthUser;
import com.spatial.service.AccessService;
import com.spatial.service.MeasurementService;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/projects/{id}/reports")
public class ReportController {
    private final DetectedObjectRepository objects;
    private final MeasurementRecordRepository records;
    private final AccessService access;

    public ReportController(DetectedObjectRepository objects, MeasurementRecordRepository records, AccessService access) {
        this.objects = objects;
        this.records = records;
        this.access = access;
    }

    /** Object inventory with the current measurements. Other report types are not implemented. */
    @GetMapping("/inventory.csv")
    public ResponseEntity<byte[]> inventory(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id) {
        access.requireProject(id, user);
        Map<UUID, Map<String, MeasurementRecord>> byObject = new HashMap<>();
        for (MeasurementRecord r : MeasurementService.current(records.findByProjectIdOrderByCreatedAtAsc(id))) {
            if (r.getObjectId() != null) {
                byObject.computeIfAbsent(r.getObjectId(), k -> new HashMap<>()).put(r.getKind(), r);
            }
        }
        StringBuilder sb = new StringBuilder("label,detector_label,detection_confidence,width_mm,height_mm,depth_mm,status\n");
        for (DetectedObject o : objects.findByProjectId(id)) {
            Map<String, MeasurementRecord> m = byObject.getOrDefault(o.getId(), Map.of());
            sb.append(csv(o.getLabel())).append(',').append(csv(o.getOriginalLabel())).append(',')
                    .append(o.getConfidence() == null ? "" : String.format("%.3f", o.getConfidence())).append(',')
                    .append(val(m.get("width"))).append(',').append(val(m.get("height"))).append(',').append(val(m.get("depth"))).append(',')
                    .append(status(List.of("width", "height", "depth"), m)).append('\n');
        }
        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=inventory.csv")
                .contentType(MediaType.parseMediaType("text/csv"))
                .body(sb.toString().getBytes(StandardCharsets.UTF_8));
    }

    private static String val(MeasurementRecord r) {
        return r == null ? "" : String.format("%.0f", r.getValueMm());
    }

    private static String status(List<String> kinds, Map<String, MeasurementRecord> m) {
        return kinds.stream().map(m::get).filter(x -> x != null).map(MeasurementRecord::getStatus).findFirst().orElse("UNMEASURED");
    }

    private static String csv(String s) {
        return "\"" + (s == null ? "" : s.replace("\"", "\"\"")) + "\"";
    }
}
