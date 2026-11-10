package com.spatial.domain;

import java.util.UUID;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ProjectRepository extends JpaRepository<Project, UUID> {
    Page<Project> findByOwnerIdOrderByCreatedAtDesc(UUID ownerId, Pageable pageable);
}
