package com.spatial.domain;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.persistence.*;
import java.util.UUID;
import lombok.Getter;
import lombok.Setter;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

@Entity
@Table(name = "navigation_nodes")
@Getter @Setter
public class NavigationNode {
    @Id @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;
    private UUID projectId;
    private int seq;
    private String label;
    private String framePath;
    private boolean panorama;
    private double x;
    private double y;
    private double z;
    private double headingRad;
    @Column(name = "time_sec")
    private Double timeSec;
    /** false for a viewpoint-only tour (video order + visual overlap): x, y, z and headingRad are then 0 and mean "unknown". */
    private boolean hasPose = true;
    private UUID roomId;
    @JdbcTypeCode(SqlTypes.JSON)
    private JsonNode camera;
}
