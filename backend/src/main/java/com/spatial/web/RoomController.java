package com.spatial.web;

import com.spatial.domain.*;
import com.spatial.security.AuthUser;
import com.spatial.service.AccessService;
import com.spatial.web.Dtos.RoomRequest;
import jakarta.validation.Valid;
import java.util.List;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

/** Rooms are confirmed by the user: viewpoints are grouped into them with PUT /api/nodes/{id}/room. */
@RestController
@RequestMapping("/api")
public class RoomController {
    private final RoomRepository rooms;
    private final NavigationNodeRepository nodes;
    private final AccessService access;

    public RoomController(RoomRepository rooms, NavigationNodeRepository nodes, AccessService access) {
        this.rooms = rooms;
        this.nodes = nodes;
        this.access = access;
    }

    @GetMapping("/projects/{id}/rooms")
    public List<Room> list(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id) {
        access.requireProject(id, user);
        return rooms.findByProjectIdOrderByCreatedAt(id);
    }

    @PostMapping("/projects/{id}/rooms")
    @ResponseStatus(HttpStatus.CREATED)
    public Room create(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id, @Valid @RequestBody RoomRequest req) {
        access.requireProject(id, user);
        Room r = new Room();
        r.setProjectId(id);
        r.setName(req.name().trim());
        if (req.kind() != null && !req.kind().isBlank()) r.setKind(req.kind());
        return rooms.save(r);
    }

    @PatchMapping("/rooms/{id}")
    public Room update(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id, @Valid @RequestBody RoomRequest req) {
        Room r = find(id, user);
        r.setName(req.name().trim());
        if (req.kind() != null && !req.kind().isBlank()) r.setKind(req.kind());
        return rooms.save(r);
    }

    @DeleteMapping("/rooms/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    @Transactional
    public void delete(@AuthenticationPrincipal AuthUser user, @PathVariable UUID id) {
        Room r = find(id, user);
        nodes.findByProjectIdOrderBySeq(r.getProjectId()).stream()
            .filter(n -> id.equals(n.getRoomId())).forEach(n -> { n.setRoomId(null); nodes.save(n); });
        rooms.delete(r);
    }

    private Room find(UUID id, AuthUser user) {
        Room r = rooms.findById(id).orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Room not found"));
        access.requireProject(r.getProjectId(), user);
        return r;
    }
}
