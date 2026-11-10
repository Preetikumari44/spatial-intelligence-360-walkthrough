package com.spatial.web;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.spatial.domain.ReconstructionAsset;
import com.spatial.domain.ReconstructionAssetRepository;
import com.spatial.security.AuthUser;
import com.spatial.service.AccessService;
import com.spatial.service.AiClient;
import com.spatial.service.StorageService;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Read-only views of what the Python reconstruction service produced and which hardware it used. */
@RestController
@RequestMapping("/api")
public class ReconstructionController {
    private final ReconstructionAssetRepository assets;
    private final AccessService access;
    private final StorageService storage;
    private final AiClient ai;
    private final ObjectMapper mapper;

    public ReconstructionController(ReconstructionAssetRepository assets, AccessService access, StorageService storage, AiClient ai,
                                    ObjectMapper mapper) {
        this.assets = assets;
        this.access = access;
        this.storage = storage;
        this.ai = ai;
        this.mapper = mapper;
    }

    /**
     * The latest reconstruction report for a project: per-stage status, the device each stage really used,
     * and every generated file (path, size, kind). "available" is false until a video job has produced one.
     */
    @GetMapping("/projects/{id}/reconstruction/outputs")
    public Map<String, Object> outputs(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id) {
        access.requireProject(id, user);
        Map<String, Object> out = new LinkedHashMap<>();
        var asset = assets.findFirstByProjectIdAndAssetTypeOrderByCreatedAtDesc(id, ReconstructionAsset.RECON_REPORT);
        if (asset.isEmpty()) {
            out.put("available", false);
            return out;
        }
        String text = storage.readTextOrEmpty(asset.get().getStoragePath());
        if (text.isEmpty()) {
            out.put("available", false);
            return out;
        }
        try {
            JsonNode report = mapper.readTree(text);
            out.put("available", true);
            out.put("jobId", asset.get().getJobId());
            out.put("report", report);
        } catch (Exception e) {
            out.put("available", false);
            out.put("error", "report.json could not be read");
        }
        return out;
    }

    /** Hardware and software detected by the AI service (CPU threads, RAM, Intel GPU, Open3D SYCL, PyTorch XPU, COLMAP). */
    @GetMapping("/ai/capabilities")
    public JsonNode capabilities(@AuthenticationPrincipal AuthUser user) {
        return ai.get("/capabilities");
    }
}
