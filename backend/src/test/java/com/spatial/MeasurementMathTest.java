package com.spatial;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.spatial.domain.MeasurementRecord;
import com.spatial.service.MeasurementService;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;

class MeasurementMathTest {

    @Test
    void referenceScaleIsMillimetresPerPixel() {
        assertEquals(2.5, MeasurementService.mmPerPixel(400, 1000), 1e-9);
    }

    @Test
    void zeroWidthReferenceIsRejected() {
        assertThrows(ResponseStatusException.class, () -> MeasurementService.mmPerPixel(0, 900));
    }

    @Test
    void newestRecordPerObjectAndKindWins() {
        UUID obj = UUID.randomUUID();
        MeasurementRecord a = rec(obj, "width", 800, "ESTIMATED");
        MeasurementRecord b = rec(obj, "height", 700, "ESTIMATED");
        MeasurementRecord c = rec(obj, "width", 850, "VERIFIED");
        List<MeasurementRecord> current = MeasurementService.current(List.of(a, b, c));
        assertEquals(2, current.size());
        assertEquals(850, current.stream().filter(r -> r.getKind().equals("width")).findFirst().get().getValueMm());
    }

    private static MeasurementRecord rec(UUID obj, String kind, double mm, String status) {
        MeasurementRecord r = new MeasurementRecord();
        r.setObjectId(obj);
        r.setKind(kind);
        r.setValueMm(mm);
        r.setStatus(status);
        return r;
    }
}
