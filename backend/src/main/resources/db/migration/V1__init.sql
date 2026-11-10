CREATE TABLE users (
    id UUID PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(100) NOT NULL,
    display_name VARCHAR(100),
    role VARCHAR(20) NOT NULL DEFAULT 'USER',
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE projects (
    id UUID PRIMARY KEY,
    owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(150) NOT NULL,
    property_type VARCHAR(50),
    status VARCHAR(30) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_projects_owner ON projects(owner_id, created_at DESC);

CREATE TABLE uploaded_media (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind VARCHAR(10) NOT NULL,
    original_name VARCHAR(255) NOT NULL,
    content_type VARCHAR(100),
    size_bytes BIGINT NOT NULL,
    storage_path VARCHAR(500) NOT NULL,
    width INT,
    height INT,
    duration_sec DOUBLE PRECISION,
    fps DOUBLE PRECISION,
    is360 BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_media_project ON uploaded_media(project_id);

CREATE TABLE processing_jobs (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    media_id UUID REFERENCES uploaded_media(id) ON DELETE SET NULL,
    type VARCHAR(30) NOT NULL,
    status VARCHAR(30) NOT NULL,
    message VARCHAR(500),
    error VARCHAR(2000),
    attempts INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);
CREATE INDEX idx_jobs_project ON processing_jobs(project_id, created_at DESC);

CREATE TABLE detected_objects (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    media_id UUID NOT NULL REFERENCES uploaded_media(id) ON DELETE CASCADE,
    job_id UUID,
    label VARCHAR(100) NOT NULL,
    original_label VARCHAR(100) NOT NULL,
    confidence DOUBLE PRECISION,
    bbox JSONB NOT NULL,
    polygon JSONB,
    edited BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX idx_objects_project ON detected_objects(project_id);
CREATE INDEX idx_objects_media ON detected_objects(media_id);

-- every measurement ever produced; the newest row per (object, kind) is the current value
CREATE TABLE measurement_records (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    object_id UUID REFERENCES detected_objects(id) ON DELETE CASCADE,
    kind VARCHAR(30) NOT NULL,
    value_mm DOUBLE PRECISION NOT NULL,
    status VARCHAR(20) NOT NULL,
    confidence DOUBLE PRECISION,
    source VARCHAR(100) NOT NULL,
    note VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_meas_project ON measurement_records(project_id, created_at DESC);
CREATE INDEX idx_meas_object ON measurement_records(object_id, kind, created_at DESC);

CREATE TABLE reconstruction_assets (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    job_id UUID,
    asset_type VARCHAR(30) NOT NULL,
    storage_path VARCHAR(500),
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_assets_project ON reconstruction_assets(project_id, asset_type);

CREATE TABLE navigation_nodes (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    seq INT NOT NULL,
    label VARCHAR(100) NOT NULL,
    frame_path VARCHAR(500) NOT NULL,
    panorama BOOLEAN NOT NULL,
    x DOUBLE PRECISION NOT NULL,
    y DOUBLE PRECISION NOT NULL,
    z DOUBLE PRECISION NOT NULL,
    heading_rad DOUBLE PRECISION NOT NULL,
    camera JSONB
);
CREATE INDEX idx_nodes_project ON navigation_nodes(project_id, seq);

CREATE TABLE navigation_connections (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    from_node_id UUID NOT NULL REFERENCES navigation_nodes(id) ON DELETE CASCADE,
    to_node_id UUID NOT NULL REFERENCES navigation_nodes(id) ON DELETE CASCADE,
    hotspot JSONB NOT NULL,
    distance_units DOUBLE PRECISION NOT NULL
);
CREATE INDEX idx_conn_from ON navigation_connections(from_node_id);
CREATE INDEX idx_conn_project ON navigation_connections(project_id);
