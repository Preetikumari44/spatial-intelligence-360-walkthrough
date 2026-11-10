package com.spatial.web;

import com.spatial.domain.Project;
import com.spatial.domain.ProjectRepository;
import com.spatial.security.AuthUser;
import com.spatial.service.AccessService;
import com.spatial.service.StorageService;
import com.spatial.web.Dtos.ProjectRequest;
import jakarta.validation.Valid;
import java.util.UUID;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/projects")
public class ProjectController {
    private final ProjectRepository projects;
    private final AccessService access;
    private final StorageService storage;

    public ProjectController(ProjectRepository projects, AccessService access, StorageService storage) {
        this.projects = projects;
        this.access = access;
        this.storage = storage;
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public Project create(@AuthenticationPrincipal AuthUser user, @Valid @RequestBody ProjectRequest req) {
        Project p = new Project();
        p.setOwnerId(user.id());
        p.setName(req.name().trim());
        p.setPropertyType(req.propertyType());
        return projects.save(p);
    }

    @GetMapping
    public Page<Project> list(@AuthenticationPrincipal AuthUser user,
                              @RequestParam(defaultValue = "0") int page,
                              @RequestParam(defaultValue = "20") int size) {
        return projects.findByOwnerIdOrderByCreatedAtDesc(user.id(), PageRequest.of(Math.max(page, 0), Math.min(Math.max(size, 1), 100)));
    }

    @GetMapping("/{id}")
    public Project get(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id) {
        return access.requireProject(id, user);
    }

    @PatchMapping("/{id}")
    public Project rename(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id, @Valid @RequestBody ProjectRequest req) {
        Project p = access.requireProject(id, user);
        p.setName(req.name().trim());
        if (req.propertyType() != null) p.setPropertyType(req.propertyType());
        return projects.save(p);
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id) {
        Project p = access.requireProject(id, user);
        projects.delete(p);
        storage.deleteProjectFiles(id);
    }
}
