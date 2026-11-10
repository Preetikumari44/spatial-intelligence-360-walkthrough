package com.spatial.service;

import com.spatial.config.AppProps;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;

/**
 * Filesystem-backed storage shared with the AI service through a mounted volume.
 * Nothing under the root is served directly; every read goes through an authenticated controller.
 */
@Service
public class StorageService {
    private final Path root;

    public StorageService(AppProps props) throws IOException {
        this.root = Path.of(props.storageRoot()).toAbsolutePath().normalize();
        Files.createDirectories(root);
    }

    public Path resolve(String relative) {
        Path p = root.resolve(relative).normalize();
        if (!p.startsWith(root)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid path");
        }
        return p;
    }

    public String saveUpload(MultipartFile file, UUID projectId, Set<String> allowedExt, long maxBytes) throws IOException {
        if (file.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Empty file");
        }
        if (file.getSize() > maxBytes) {
            throw new ResponseStatusException(HttpStatus.PAYLOAD_TOO_LARGE, "File exceeds " + (maxBytes / (1024 * 1024)) + " MB");
        }
        String ext = extensionOf(file.getOriginalFilename());
        if (!allowedExt.contains(ext)) {
            throw new ResponseStatusException(HttpStatus.UNSUPPORTED_MEDIA_TYPE, "Unsupported file type ." + ext + ", allowed: " + allowedExt);
        }
        String rel = "projects/" + projectId + "/media/" + UUID.randomUUID() + "." + ext;
        Path target = resolve(rel);
        Files.createDirectories(target.getParent());
        try (InputStream in = file.getInputStream()) {
            Files.copy(in, target, StandardCopyOption.REPLACE_EXISTING);
        }
        return rel;
    }

    public void deleteProjectFiles(UUID projectId) {
        Path dir = resolve("projects/" + projectId);
        if (!Files.exists(dir)) {
            return;
        }
        try (var walk = Files.walk(dir)) {
            walk.sorted(java.util.Comparator.reverseOrder()).forEach(p -> p.toFile().delete());
        } catch (IOException ignored) {
            // leftover files are harmless; the DB rows are already gone
        }
    }

    /** Appends a line to a text file under the storage root (job logs). Logging must never fail a job, so errors are swallowed. */
    public void appendLine(String relative, String line) {
        try {
            Path p = resolve(relative);
            Files.createDirectories(p.getParent());
            Files.writeString(p, line + System.lineSeparator(), java.nio.charset.StandardCharsets.UTF_8,
                    java.nio.file.StandardOpenOption.CREATE, java.nio.file.StandardOpenOption.APPEND);
        } catch (IOException | RuntimeException ignored) {
        }
    }

    public String readTextOrEmpty(String relative) {
        try {
            Path p = resolve(relative);
            return Files.isRegularFile(p) ? Files.readString(p, java.nio.charset.StandardCharsets.UTF_8) : "";
        } catch (IOException | RuntimeException e) {
            return "";
        }
    }

    public void deleteQuietly(String relative) {
        try {
            Files.deleteIfExists(resolve(relative));
        } catch (IOException ignored) {
        }
    }

    public static String extensionOf(String name) {
        if (name == null || !name.contains(".")) {
            return "";
        }
        return name.substring(name.lastIndexOf('.') + 1).toLowerCase(Locale.ROOT);
    }
}
