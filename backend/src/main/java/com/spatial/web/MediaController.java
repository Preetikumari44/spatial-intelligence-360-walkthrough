package com.spatial.web;

import com.fasterxml.jackson.databind.JsonNode;
import com.spatial.domain.*;
import com.spatial.security.AuthUser;
import com.spatial.service.AccessService;
import com.spatial.service.AiClient;
import com.spatial.service.AiException;
import com.spatial.service.StorageService;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.Resource;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api")
public class MediaController {
    private static final Set<String> IMAGE_EXT = Set.of("jpg", "jpeg", "png", "webp");
    private static final Set<String> VIDEO_EXT = Set.of("mp4", "mov", "avi", "webm", "mkv");
    private static final long MAX_IMAGE = 25L * 1024 * 1024;
    private static final long MAX_VIDEO = 2L * 1024 * 1024 * 1024;

    private final UploadedMediaRepository media;
    private final AccessService access;
    private final StorageService storage;
    private final AiClient ai;

    public MediaController(UploadedMediaRepository media, AccessService access, StorageService storage, AiClient ai) {
        this.media = media;
        this.access = access;
        this.storage = storage;
        this.ai = ai;
    }

    @PostMapping("/projects/{id}/images")
    @ResponseStatus(HttpStatus.CREATED)
    public List<UploadedMedia> uploadImages(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id,
                                            @RequestParam("files") MultipartFile[] files) throws IOException {
        access.requireProject(id, user);
        List<UploadedMedia> saved = new ArrayList<>();
        for (MultipartFile f : files) {
            String rel = storage.saveUpload(f, id, IMAGE_EXT, MAX_IMAGE);
            saved.add(media.save(build(id, "IMAGE", f, rel)));
        }
        return saved;
    }

    @PostMapping("/projects/{id}/videos")
    @ResponseStatus(HttpStatus.CREATED)
    public UploadedMedia uploadVideo(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id,
                                     @RequestParam("file") MultipartFile file,
                                     @RequestParam(defaultValue = "false") boolean is360) throws IOException {
        access.requireProject(id, user);
        String rel = storage.saveUpload(file, id, VIDEO_EXT, MAX_VIDEO);
        UploadedMedia m = build(id, "VIDEO", file, rel);
        m.set360(is360);
        try {
            // the AI service opens the file, so corrupt or unreadable videos are rejected here, not mid-job
            JsonNode probe = ai.post("/video/probe", Map.of("video_path", rel, "is_360", is360));
            m.setWidth(probe.path("width").asInt());
            m.setHeight(probe.path("height").asInt());
            m.setDurationSec(probe.path("duration_sec").asDouble());
            m.setFps(probe.path("fps").asDouble());
        } catch (AiException e) {
            storage.deleteQuietly(rel);
            if (e.isClientError()) {
                throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, e.getMessage());
            }
            throw e;
        }
        return media.save(m);
    }

    @GetMapping("/projects/{id}/media")
    public List<UploadedMedia> list(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id) {
        access.requireProject(id, user);
        return media.findByProjectIdOrderByCreatedAtDesc(id);
    }

    @GetMapping("/media/{id}")
    public UploadedMedia meta(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id) {
        return owned(id, user);
    }

    @GetMapping("/media/{id}/content")
    public ResponseEntity<Resource> content(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id) {
        UploadedMedia m = owned(id, user);
        return stream(storage.resolve(m.getStoragePath()), m.getContentType());
    }

    /** Frames, panoramas and point-cloud previews written by the AI service, served only to the project's owner. */
    @GetMapping("/projects/{id}/files")
    public ResponseEntity<Resource> projectFile(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id, @RequestParam String path,
                                                @RequestParam(defaultValue = "false") boolean download) {
        access.requireProject(id, user);
        Path projectRoot = storage.resolve("projects/" + id);
        Path file = storage.resolve(path);
        if (!file.startsWith(projectRoot)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "File not found");
        }
        ResponseEntity<Resource> res = stream(file, null);
        if (!download) {
            return res;
        }
        return ResponseEntity.ok().headers(res.getHeaders())
                .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"" + file.getFileName().toString().replace("\"", "") + "\"")
                .body(res.getBody());
    }

    private ResponseEntity<Resource> stream(Path file, String contentType) {
        if (!Files.isRegularFile(file)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "File not found");
        }
        String name = file.getFileName().toString().toLowerCase();
        String type = switch (name.substring(name.lastIndexOf('.') + 1)) {
            case "mp4" -> "video/mp4";
            case "mov" -> "video/quicktime";
            case "avi" -> "video/x-msvideo";
            case "webm" -> "video/webm";
            case "mkv" -> "video/x-matroska";
            default -> contentType;
        };
        if (type == null) {
            if (name.endsWith(".json")) {
                type = "application/json";
            } else if (name.endsWith(".png")) {
                type = "image/png";
            } else if (name.endsWith(".ply") || name.endsWith(".splat") || name.endsWith(".spz")) {
                type = "application/octet-stream";
            } else if (name.endsWith(".obj") || name.endsWith(".log")) {
                type = "text/plain";
            } else {
                type = "image/jpeg";
            }
        }
        return ResponseEntity.ok()
                .contentType(MediaType.parseMediaType(type))
                .header("Accept-Ranges", "bytes")
                .cacheControl(CacheControl.noStore())
                .body(new FileSystemResource(file));
    }

    private UploadedMedia owned(UUID mediaId, AuthUser user) {
        UploadedMedia m = media.findById(mediaId).orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Media not found"));
        access.requireProject(m.getProjectId(), user);
        return m;
    }

    private UploadedMedia build(UUID projectId, String kind, MultipartFile f, String rel) {
        UploadedMedia m = new UploadedMedia();
        m.setProjectId(projectId);
        m.setKind(kind);
        String name = f.getOriginalFilename() == null ? "upload" : Path.of(f.getOriginalFilename()).getFileName().toString();
        m.setOriginalName(name);
        m.setContentType(f.getContentType());
        m.setSizeBytes(f.getSize());
        m.setStoragePath(rel);
        return m;
    }
}
