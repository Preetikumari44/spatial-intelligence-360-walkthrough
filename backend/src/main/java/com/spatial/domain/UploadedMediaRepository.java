package com.spatial.domain;

import java.util.List;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface UploadedMediaRepository extends JpaRepository<UploadedMedia, UUID> {
    List<UploadedMedia> findByProjectIdOrderByCreatedAtDesc(UUID projectId);
}
