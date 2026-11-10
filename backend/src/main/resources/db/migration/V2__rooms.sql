-- Rooms are user-confirmed groupings of viewpoints (automatic room detection is not implemented).
CREATE TABLE rooms (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    kind VARCHAR(30) NOT NULL DEFAULT 'OTHER',
    source VARCHAR(10) NOT NULL DEFAULT 'MANUAL',
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_rooms_project ON rooms(project_id);

ALTER TABLE navigation_nodes ADD COLUMN room_id UUID REFERENCES rooms(id) ON DELETE SET NULL;
CREATE INDEX idx_nodes_room ON navigation_nodes(room_id);
