package com.spatial.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

class TourManifestNormalizationTest {
    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    void preservesCompleteCoverageAndWarnings() throws Exception {
        JsonNode manifest = normalize("""
                {"coverage":{"registered_images":8,"total_images":10,"registered_fraction":0.8,
                  "untracked_time_ranges_sec":[[2.0,4.0]]},"warnings":["Partial coverage"]}
                """);

        JsonNode coverage = manifest.path("coverage");
        assertTrue(coverage.path("available").asBoolean());
        assertEquals(8, coverage.path("registered_images").asInt());
        assertEquals(10, coverage.path("total_images").asInt());
        assertEquals(0.8, coverage.path("registered_fraction").asDouble(), 1e-9);
        assertEquals(1, coverage.path("untracked_time_ranges_sec").size());
        assertEquals("Partial coverage", manifest.path("warnings").get(0).asText());
    }

    @Test
    void missingCoverageGetsUnavailableDefaults() throws Exception {
        JsonNode manifest = normalize("{\"floorplan\":{\"points\":[]}}");
        JsonNode coverage = manifest.path("coverage");

        assertFalse(coverage.path("available").asBoolean());
        assertEquals(0, coverage.path("registered_images").asInt());
        assertEquals(0, coverage.path("total_images").asInt());
        assertEquals(0, coverage.path("registered_fraction").asDouble(), 1e-9);
        assertTrue(coverage.path("untracked_time_ranges_sec").isArray());
        assertEquals(0, coverage.path("untracked_time_ranges_sec").size());
        assertEquals(0, manifest.path("warnings").size());
    }

    @Test
    void missingUntrackedRangesAndWarningsGetEmptyArrays() throws Exception {
        JsonNode manifest = normalize("{\"coverage\":{\"registered_images\":3,\"total_images\":4}}");

        assertTrue(manifest.path("coverage").path("available").asBoolean());
        assertTrue(manifest.path("coverage").path("untracked_time_ranges_sec").isArray());
        assertEquals(0, manifest.path("coverage").path("untracked_time_ranges_sec").size());
        assertTrue(manifest.path("warnings").isArray());
        assertEquals(0, manifest.path("warnings").size());
    }

    @Test
    void olderManifestRemainsReadableAndCoverageIsMarkedUnavailable() throws Exception {
        JsonNode manifest = normalize("""
                {"extents":{"x":1,"y":2,"z":3},"points_path":"old/points.json",
                  "floorplan":{"points":[],"bounds":{"minx":0,"maxx":1,"minz":0,"maxz":1},"note":"legacy"}}
                """);

        assertEquals("old/points.json", manifest.path("points_path").asText());
        assertEquals("legacy", manifest.path("floorplan").path("note").asText());
        assertFalse(manifest.path("coverage").path("available").asBoolean());
    }

    @Test
    void invalidCountsAndRangesAreNormalizedWithoutInventingCoverage() throws Exception {
        JsonNode manifest = normalize("""
                {"coverage":{"registered_images":-4,"total_images":2,"registered_fraction":7,
                  "untracked_time_ranges_sec":[[-1,2],[5,4],[1,3]]}}
                """);
        JsonNode coverage = manifest.path("coverage");

        assertFalse(coverage.path("available").asBoolean());
        assertEquals(0, coverage.path("registered_images").asInt());
        assertEquals(2, coverage.path("total_images").asInt());
        assertEquals(0, coverage.path("registered_fraction").asDouble(), 1e-9);
        assertEquals(1, coverage.path("untracked_time_ranges_sec").size());
        assertEquals(1, coverage.path("untracked_time_ranges_sec").get(0).get(0).asInt());
    }

    private JsonNode normalize(String source) throws Exception {
        return MeasurementService.normalizeManifest(mapper.readTree(source), mapper);
    }
}
