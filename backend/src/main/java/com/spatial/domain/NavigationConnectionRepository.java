package com.spatial.domain;

import java.util.List;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.transaction.annotation.Transactional;

public interface NavigationConnectionRepository extends JpaRepository<NavigationConnection, UUID> {
    List<NavigationConnection> findByProjectId(UUID projectId);

    @Transactional
    void deleteByProjectId(UUID projectId);
}
