package com.spatial.domain;

import java.util.List;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface MeasurementRecordRepository extends JpaRepository<MeasurementRecord, UUID> {
    List<MeasurementRecord> findByProjectIdOrderByCreatedAtAsc(UUID projectId);

    List<MeasurementRecord> findByObjectIdOrderByCreatedAtAsc(UUID objectId);
}
