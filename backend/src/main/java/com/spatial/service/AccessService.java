package com.spatial.service;

import com.spatial.domain.Project;
import com.spatial.domain.ProjectRepository;
import com.spatial.security.AuthUser;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

@Service
public class AccessService {
    private final ProjectRepository projects;

    public AccessService(ProjectRepository projects) {
        this.projects = projects;
    }

    /** Returns the project if the caller owns it (or is an admin); otherwise 404 so ids are not probeable. */
    public Project requireProject(UUID projectId, AuthUser user) {
        Project p = projects.findById(projectId).orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Project not found"));
        if (!p.getOwnerId().equals(user.id()) && !user.isAdmin()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Project not found");
        }
        return p;
    }
}
