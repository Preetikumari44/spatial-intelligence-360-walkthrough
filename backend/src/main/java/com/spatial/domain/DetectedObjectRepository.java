package com.spatial.domain;

import java.util.List;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.transaction.annotation.Transactional;

public interface DetectedObjectRepository extends JpaRepository<DetectedObject, UUID> {
    List<DetectedObject> findByProjectId(UUID projectId);

    List<DetectedObject> findByMediaId(UUID mediaId);

    @Transactional
    void deleteByMediaId(UUID mediaId);
}
