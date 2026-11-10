-- Virtual tours built from video frames alone (no COLMAP) have viewpoints but no 3D camera pose.
-- Existing rows keep has_pose = TRUE (they all came from a pose reconstruction). Purely additive; nothing is dropped or rewritten.
ALTER TABLE navigation_nodes ADD COLUMN has_pose BOOLEAN NOT NULL DEFAULT TRUE;
