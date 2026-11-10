package com.spatial.web;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.spatial.domain.*;
import com.spatial.security.AuthUser;
import com.spatial.service.AccessService;
import com.spatial.service.AiClient;
import com.spatial.service.MeasurementService;
import com.spatial.service.StorageService;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.core.io.FileSystemResource;
import org.springframework.http.HttpHeaders;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.method.annotation.AuthenticationPrincipalArgumentResolver;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;

class VirtualWalkthroughApiTest {
    @TempDir
    Path tempDir;

    private UploadedMediaRepository media;
    private StorageService storage;
    private AccessService access;
    private AiClient ai;
    private MockMvc mockMvc;
    private AuthUser user;

    @BeforeEach
    void setUp() {
        media = mock(UploadedMediaRepository.class);
        storage = mock(StorageService.class);
        access = mock(AccessService.class);
        ai = mock(AiClient.class);
        user = new AuthUser(UUID.randomUUID(), "owner@example.test", "USER");
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(user, null, List.of()));
        MediaController controller = new MediaController(media, access, storage, ai);
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .setCustomArgumentResolvers(new AuthenticationPrincipalArgumentResolver())
                .build();
    }

    @AfterEach
    void clearSecurityContext() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void authenticatedVideoContentHasMp4MimeAndSupportsByteRanges() throws Exception {
        UUID mediaId = UUID.randomUUID();
        UUID projectId = UUID.randomUUID();
        Path mp4 = tempDir.resolve("walkthrough.mp4");
        byte[] bytes = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9};
        Files.write(mp4, bytes);
        UploadedMedia uploaded = new UploadedMedia();
        uploaded.setId(mediaId);
        uploaded.setProjectId(projectId);
        uploaded.setStoragePath("projects/" + projectId + "/media/walkthrough.mp4");
        uploaded.setContentType(null);
        when(media.findById(mediaId)).thenReturn(Optional.of(uploaded));
        when(storage.resolve(uploaded.getStoragePath())).thenReturn(mp4);

        mockMvc.perform(get("/api/media/{id}/content", mediaId).header(HttpHeaders.RANGE, "bytes=2-5"))
                .andExpect(status().isPartialContent())
                .andExpect(header().string(HttpHeaders.CONTENT_TYPE, "video/mp4"))
                .andExpect(header().string(HttpHeaders.ACCEPT_RANGES, "bytes"))
                .andExpect(header().string(HttpHeaders.CONTENT_RANGE, "bytes 2-5/10"))
                .andExpect(content().bytes(new byte[] {2, 3, 4, 5}));
    }

    @Test
    void aviUploadIsAcceptedWhenTheAiProbeCanDecodeIt() throws Exception {
        UUID projectId = UUID.randomUUID();
        String storagePath = "projects/" + projectId + "/media/walkthrough.avi";
        when(storage.saveUpload(org.mockito.ArgumentMatchers.any(MultipartFile.class),
                org.mockito.ArgumentMatchers.eq(projectId), org.mockito.ArgumentMatchers.anySet(),
                org.mockito.ArgumentMatchers.anyLong())).thenReturn(storagePath);
        JsonNode probe = new ObjectMapper().readTree(
                "{\"width\":640,\"height\":480,\"duration_sec\":2.0,\"fps\":30.0}");
        when(ai.post(org.mockito.ArgumentMatchers.eq("/video/probe"), org.mockito.ArgumentMatchers.anyMap()))
                .thenReturn(probe);

        MediaController controller = new MediaController(media, access, storage, ai);
        controller.uploadVideo(user, projectId,
                new MockMultipartFile("file", "walkthrough.avi", "video/x-msvideo", new byte[] {1, 2, 3}), false);

        verify(storage).saveUpload(org.mockito.ArgumentMatchers.any(MultipartFile.class),
                org.mockito.ArgumentMatchers.eq(projectId),
                org.mockito.ArgumentMatchers.argThat(extensions -> extensions.contains("avi")),
                org.mockito.ArgumentMatchers.anyLong());
    }

    @Test
    void authenticatedAviContentUsesAviMimeType() throws Exception {
        UUID mediaId = UUID.randomUUID();
        UUID projectId = UUID.randomUUID();
        Path avi = tempDir.resolve("walkthrough.avi");
        Files.write(avi, new byte[] {1, 2, 3});
        UploadedMedia uploaded = new UploadedMedia();
        uploaded.setId(mediaId);
        uploaded.setProjectId(projectId);
        uploaded.setStoragePath("projects/" + projectId + "/media/walkthrough.avi");
        when(media.findById(mediaId)).thenReturn(Optional.of(uploaded));
        when(storage.resolve(uploaded.getStoragePath())).thenReturn(avi);

        mockMvc.perform(get("/api/media/{id}/content", mediaId))
                .andExpect(status().isOk())
                .andExpect(header().string(HttpHeaders.CONTENT_TYPE, "video/x-msvideo"));
    }

    @Test
    void projectFrameIsServedAsJpeg() throws Exception {
        UUID projectId = UUID.randomUUID();
        String relative = "projects/" + projectId + "/jobs/job/frames/frame.jpg";
        Path projectRoot = tempDir.resolve(projectId.toString());
        Path image = projectRoot.resolve("frame.jpg");
        byte[] bytes = {(byte) 0xff, (byte) 0xd8, 1, 2, (byte) 0xff, (byte) 0xd9};
        Files.createDirectories(projectRoot);
        Files.write(image, bytes);
        when(storage.resolve("projects/" + projectId)).thenReturn(projectRoot);
        when(storage.resolve(relative)).thenReturn(image);

        mockMvc.perform(get("/api/projects/{id}/files", projectId).param("path", relative))
                .andExpect(status().isOk())
                .andExpect(header().string(HttpHeaders.CONTENT_TYPE, "image/jpeg"))
                .andExpect(content().bytes(bytes));
    }

    @Test
    void tourIdentifiesSourceVideoFromTheOwningReconstructionJob() {
        UUID projectId = UUID.randomUUID();
        UUID jobId = UUID.randomUUID();
        UUID mediaId = UUID.randomUUID();
        NavigationNodeRepository nodes = mock(NavigationNodeRepository.class);
        NavigationConnectionRepository connections = mock(NavigationConnectionRepository.class);
        RoomRepository rooms = mock(RoomRepository.class);
        ReconstructionAssetRepository assets = mock(ReconstructionAssetRepository.class);
        ProcessingJobRepository jobs = mock(ProcessingJobRepository.class);
        MeasurementService measurements = mock(MeasurementService.class);

        when(nodes.findByProjectIdOrderBySeq(projectId)).thenReturn(List.of());
        when(connections.findByProjectId(projectId)).thenReturn(List.of());
        when(rooms.findByProjectIdOrderByCreatedAt(projectId)).thenReturn(List.of());
        when(measurements.manifest(projectId)).thenReturn(Optional.empty());
        when(measurements.reconstructionSummary(projectId)).thenReturn(Map.of("available", false));

        ReconstructionAsset manifest = new ReconstructionAsset();
        manifest.setJobId(jobId);
        when(assets.findFirstByProjectIdAndAssetTypeOrderByCreatedAtDesc(projectId, ReconstructionAsset.TOUR_MANIFEST))
                .thenReturn(Optional.of(manifest));
        ProcessingJob job = new ProcessingJob();
        job.setId(jobId);
        job.setProjectId(projectId);
        job.setMediaId(mediaId);
        job.setType("VIDEO_RECONSTRUCTION");
        when(jobs.findById(jobId)).thenReturn(Optional.of(job));

        TourController controller = new TourController(nodes, connections, access, measurements, rooms, assets, jobs,
                storage, new ObjectMapper());
        Map<String, Object> response = controller.tour(user, projectId);

        assertEquals(mediaId, response.get("sourceVideoId"));
    }

    @Test
    void tourRecoversMissingViewpointTimesFromStoredFrameIndexWithoutSavingRows() throws Exception {
        UUID projectId = UUID.randomUUID();
        UUID jobId = UUID.randomUUID();
        UUID mediaId = UUID.randomUUID();
        String framePath = "projects/" + projectId + "/jobs/" + jobId + "/frames/f_000035.jpg";
        String indexPath = "projects/" + projectId + "/jobs/" + jobId + "/frames/frames.json";
        Path frameIndex = tempDir.resolve("frames.json");
        Files.writeString(frameIndex, "{\"frames\":[{\"file\":\"" + framePath + "\",\"t\":0.583}]}");

        NavigationNode node = new NavigationNode();
        node.setProjectId(projectId);
        node.setFramePath(framePath);
        NavigationNodeRepository nodes = mock(NavigationNodeRepository.class);
        NavigationConnectionRepository connections = mock(NavigationConnectionRepository.class);
        RoomRepository rooms = mock(RoomRepository.class);
        ReconstructionAssetRepository assets = mock(ReconstructionAssetRepository.class);
        ProcessingJobRepository jobs = mock(ProcessingJobRepository.class);
        MeasurementService measurements = mock(MeasurementService.class);
        StorageService tourStorage = mock(StorageService.class);

        when(nodes.findByProjectIdOrderBySeq(projectId)).thenReturn(List.of(node));
        when(connections.findByProjectId(projectId)).thenReturn(List.of());
        when(rooms.findByProjectIdOrderByCreatedAt(projectId)).thenReturn(List.of());
        when(measurements.manifest(projectId)).thenReturn(Optional.empty());
        when(measurements.reconstructionSummary(projectId)).thenReturn(Map.of("available", false));
        when(tourStorage.resolve(indexPath)).thenReturn(frameIndex);

        ReconstructionAsset manifest = new ReconstructionAsset();
        manifest.setJobId(jobId);
        when(assets.findFirstByProjectIdAndAssetTypeOrderByCreatedAtDesc(projectId, ReconstructionAsset.TOUR_MANIFEST))
                .thenReturn(Optional.of(manifest));
        ProcessingJob job = new ProcessingJob();
        job.setId(jobId);
        job.setProjectId(projectId);
        job.setMediaId(mediaId);
        job.setType("VIDEO_RECONSTRUCTION");
        when(jobs.findById(jobId)).thenReturn(Optional.of(job));

        TourController controller = new TourController(nodes, connections, access, measurements, rooms, assets, jobs,
                tourStorage, new ObjectMapper());
        controller.tour(user, projectId);

        assertEquals(Double.valueOf(0.583), node.getTimeSec());
        verify(nodes, never()).save(org.mockito.ArgumentMatchers.any(NavigationNode.class));
    }
}
