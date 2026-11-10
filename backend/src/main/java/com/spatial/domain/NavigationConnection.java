package com.spatial.domain;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.persistence.*;
import java.util.UUID;
import lombok.Getter;
import lombok.Setter;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

@Entity
@Table(name = "navigation_connections")
@Getter @Setter
public class NavigationConnection {
    @Id @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;
    private UUID projectId;
    private UUID fromNodeId;
    private UUID toNodeId;
    @JdbcTypeCode(SqlTypes.JSON)
    private JsonNode hotspot;
    private double distanceUnits;
}
