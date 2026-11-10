package com.spatial.domain;

import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.transaction.annotation.Transactional;

public interface ReconstructionAssetRepository extends JpaRepository<ReconstructionAsset, UUID> {
    Optional<ReconstructionAsset> findFirstByProjectIdAndAssetTypeOrderByCreatedAtDesc(UUID projectId, String assetType);

    @Transactional
    void deleteByProjectIdAndAssetType(UUID projectId, String assetType);
}
