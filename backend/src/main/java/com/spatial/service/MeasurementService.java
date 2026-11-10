package com.spatial.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.spatial.domain.*;
import com.spatial.web.Dtos.ImageCalibration;
import com.spatial.web.Dtos.MeasurementPatch;
import com.spatial.web.Dtos.VideoCalibration;
import java.io.IOException;
import java.nio.file.Files;
import java.util.*;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

@Service
public class MeasurementService {
    private final MeasurementRecordRepository records;
    private final DetectedObjectRepository objects;
    private final NavigationNodeRepository nodes;
    private final ReconstructionAssetRepository assets;
    private final StorageService storage;
    private final ProcessingService processing;
    private final ObjectMapper mapper;

    public MeasurementService(MeasurementRecordRepository records, DetectedObjectRepository objects, NavigationNodeRepository nodes,
                              ReconstructionAssetRepository assets, StorageService storage, ProcessingService processing, ObjectMapper mapper) {
        this.records = records;
        this.objects = objects;
        this.nodes = nodes;
        this.assets = assets;
        this.storage = storage;
        this.processing = processing;
        this.mapper = mapper;
    }

    /** Newest record per (object, kind). The input must be ordered oldest first. */
    public static List<MeasurementRecord> current(List<MeasurementRecord> ordered) {
        Map<String, MeasurementRecord> latest = new LinkedHashMap<>();
        for (MeasurementRecord r : ordered) {
            latest.put(r.getObjectId() + ":" + r.getKind(), r);
        }
        return new ArrayList<>(latest.values());
    }

    /**
     * Single-photo calibration: one object of known real width fixes a mm-per-pixel factor.
     * That factor is only valid for objects roughly the same distance from the camera and facing it,
     * so the resulting records are CALIBRATED but carry no confidence number.
     */
    public List<MeasurementRecord> calibrateImage(UUID projectId, ImageCalibration req) {
        DetectedObject ref = objects.findById(req.referenceObjectId())
                .filter(o -> o.getProjectId().equals(projectId))
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Reference object not found"));
        double mmPerPx = mmPerPixel(widthPx(ref), req.realWidthMm());
        String note = "Scale from reference '" + ref.getLabel() + "'. Valid only for objects at a similar distance and facing the camera.";
        List<MeasurementRecord> out = new ArrayList<>();
        for (DetectedObject o : objects.findByMediaId(ref.getMediaId())) {
            out.add(save(projectId, o.getId(), "width", widthPx(o) * mmPerPx, "CALIBRATED", "reference-calibration", note));
            out.add(save(projectId, o.getId(), "height", heightPx(o) * mmPerPx, "CALIBRATED", "reference-calibration", note));
        }
        return out;
    }

    public static double mmPerPixel(double widthPx, double realWidthMm) {
        if (widthPx <= 0) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "Reference object has no measurable width");
        }
        return realWidthMm / widthPx;
    }

    public MeasurementRecord patch(UUID id, UUID projectId, MeasurementPatch req) {
        MeasurementRecord old = records.findById(id)
                .filter(r -> r.getProjectId().equals(projectId))
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Measurement not found"));
        // history is append-only: an edit becomes a new VERIFIED record that supersedes the old one
        return save(projectId, old.getObjectId(), old.getKind(), req.valueMm(), "VERIFIED", "user", req.note());
    }

    public Map<String, Object> calibrateVideo(UUID projectId, VideoCalibration req, UUID jobId) {
        Map<UUID, NavigationNode> byId = new HashMap<>();
        nodes.findByProjectIdOrderBySeq(projectId).forEach(n -> byId.put(n.getId(), n));
        NavigationNode a = byId.get(req.nodeAId());
        NavigationNode b = byId.get(req.nodeBId());
        if (a == null || b == null || a.getId().equals(b.getId())) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Pick two different viewpoints from this project");
        }
        if (!a.isHasPose() || !b.isHasPose()) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,
                "This tour has no 3D camera positions (viewpoint-only tour), so distances cannot be calibrated. Run the advanced 3D reconstruction first.");
        }
        double model = Math.sqrt(Math.pow(a.getX() - b.getX(), 2) + Math.pow(a.getY() - b.getY(), 2) + Math.pow(a.getZ() - b.getZ(), 2));
        if (model < 1e-9) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "Viewpoints share a position; choose two that are further apart");
        }
        double mmPerUnit = req.realDistanceMm() / model;
        assets.deleteByProjectIdAndAssetType(projectId, ReconstructionAsset.SCALE);
        ReconstructionAsset s = new ReconstructionAsset();
        s.setProjectId(projectId);
        s.setJobId(jobId);
        s.setAssetType(ReconstructionAsset.SCALE);
        s.setMetadata(processing.scaleMetadata(mmPerUnit, a.getId(), b.getId(), req.realDistanceMm(), model));
        assets.save(s);
        return reconstructionSummary(projectId);
    }

    public Optional<Double> mmPerUnit(UUID projectId) {
        return assets.findFirstByProjectIdAndAssetTypeOrderByCreatedAtDesc(projectId, ReconstructionAsset.SCALE)
                .map(a -> a.getMetadata().path("mmPerUnit").asDouble());
    }

    public Optional<JsonNode> manifest(UUID projectId) {
        return assets.findFirstByProjectIdAndAssetTypeOrderByCreatedAtDesc(projectId, ReconstructionAsset.TOUR_MANIFEST).map(a -> {
            try {
                return normalizeManifest(mapper.readTree(Files.readString(storage.resolve(a.getStoragePath()))), mapper);
            } catch (IOException e) {
                throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, "Tour manifest is missing on disk");
            }
        });
    }

    static JsonNode normalizeManifest(JsonNode source, ObjectMapper mapper) {
        ObjectNode manifest = source != null && source.isObject()
                ? (ObjectNode) source.deepCopy() : mapper.createObjectNode();
        JsonNode originalCoverage = manifest.get("coverage");
        ObjectNode coverage = originalCoverage != null && originalCoverage.isObject()
                ? (ObjectNode) originalCoverage.deepCopy() : mapper.createObjectNode();
        Long registeredValue = nonNegativeInteger(coverage.get("registered_images"));
        Long totalValue = nonNegativeInteger(coverage.get("total_images"));
        boolean available = originalCoverage != null && originalCoverage.isObject()
                && registeredValue != null && totalValue != null;
        long registered = registeredValue == null ? 0 : registeredValue;
        long total = totalValue == null ? registered : Math.max(totalValue, registered);

        coverage.put("available", available);
        coverage.put("registered_images", registered);
        coverage.put("total_images", total);
        coverage.put("registered_fraction", total == 0 ? 0.0 : (double) registered / total);

        ArrayNode ranges = mapper.createArrayNode();
        JsonNode originalRanges = coverage.get("untracked_time_ranges_sec");
        if (originalRanges != null && originalRanges.isArray()) {
            for (JsonNode range : originalRanges) {
                if (range.isArray() && range.size() == 2 && finiteNonNegative(range.get(0))
                        && finiteNonNegative(range.get(1)) && range.get(1).asDouble() >= range.get(0).asDouble()) {
                    ArrayNode normalizedRange = mapper.createArrayNode();
                    normalizedRange.add(range.get(0).asDouble());
                    normalizedRange.add(range.get(1).asDouble());
                    ranges.add(normalizedRange);
                }
            }
        }
        coverage.set("untracked_time_ranges_sec", ranges);
        manifest.set("coverage", coverage);

        ArrayNode warnings = mapper.createArrayNode();
        JsonNode originalWarnings = manifest.get("warnings");
        if (originalWarnings != null && originalWarnings.isArray()) {
            originalWarnings.forEach(warning -> {
                if (warning.isTextual()) warnings.add(warning.asText());
            });
        }
        manifest.set("warnings", warnings);
        return manifest;
    }

    private static Long nonNegativeInteger(JsonNode value) {
        if (value == null || !value.isIntegralNumber() || !value.canConvertToLong() || value.asLong() < 0) return null;
        return value.asLong();
    }

    private static boolean finiteNonNegative(JsonNode value) {
        return value != null && value.isNumber() && Double.isFinite(value.asDouble()) && value.asDouble() >= 0;
    }

    /** Overall extents of the reconstructed point cloud: not room-by-room, and only metric once a scale exists. */
    public Map<String, Object> reconstructionSummary(UUID projectId) {
        Map<String, Object> out = new LinkedHashMap<>();
        Optional<JsonNode> m = manifest(projectId);
        if (m.isEmpty()) {
            out.put("available", false);
            return out;
        }
        Optional<Double> scale = mmPerUnit(projectId);
        JsonNode ext = m.get().path("extents");
        Map<String, Object> units = new LinkedHashMap<>();
        Map<String, Object> mm = new LinkedHashMap<>();
        for (String axis : List.of("x", "y", "z")) {
            double u = ext.path(axis).asDouble();
            units.put(axis, u);
            scale.ifPresent(s -> mm.put(axis, u * s));
        }
        out.put("available", true);
        out.put("extentsModelUnits", units);
        out.put("extentsMm", scale.isPresent() ? mm : null);
        out.put("mmPerUnit", scale.orElse(null));
        out.put("status", scale.isPresent() ? "CALIBRATED" : "UNCALIBRATED");
        out.put("note", "Extents of the sparse point cloud (x/z horizontal, y vertical). Room segmentation, floor area and ceiling height are not computed.");
        return out;
    }

    private MeasurementRecord save(UUID projectId, UUID objectId, String kind, double mm, String status, String source, String note) {
        MeasurementRecord r = new MeasurementRecord();
        r.setProjectId(projectId);
        r.setObjectId(objectId);
        r.setKind(kind);
        r.setValueMm(mm);
        r.setStatus(status);
        r.setSource(source);
        r.setNote(note);
        return records.save(r);
    }

    private static double widthPx(DetectedObject o) {
        return o.getBbox().get(2).asDouble() - o.getBbox().get(0).asDouble();
    }

    private static double heightPx(DetectedObject o) {
        return o.getBbox().get(3).asDouble() - o.getBbox().get(1).asDouble();
    }
}
