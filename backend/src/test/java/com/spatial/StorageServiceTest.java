package com.spatial;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.spatial.config.AppProps;
import com.spatial.service.StorageService;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.web.server.ResponseStatusException;

class StorageServiceTest {

    @TempDir
    Path tmp;

    @Test
    void pathTraversalIsRejected() throws Exception {
        StorageService s = new StorageService(new AppProps(tmp.toString(), "http://x", "s".repeat(40), 60, "*"));
        assertThrows(ResponseStatusException.class, () -> s.resolve("../outside.txt"));
    }

    @Test
    void extensionParsing() {
        assertEquals("jpg", StorageService.extensionOf("Room.JPG"));
        assertEquals("", StorageService.extensionOf("noext"));
    }
}
