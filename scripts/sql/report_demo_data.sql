-- READ-ONLY. Shows what the database holds so you can confirm what is demo/test data before anything is deleted.
\echo === Accounts (these are NEVER touched by the cleanup) ===
SELECT id, email, role, created_at FROM users ORDER BY created_at;

\echo === Projects per owner ===
SELECT u.email AS owner, p.id AS project_id, p.name, p.property_type, p.status, p.created_at,
       (SELECT count(*) FROM uploaded_media m WHERE m.project_id = p.id)          AS media,
       (SELECT count(*) FROM processing_jobs j WHERE j.project_id = p.id)         AS jobs,
       (SELECT count(*) FROM navigation_nodes n WHERE n.project_id = p.id)        AS viewpoints,
       (SELECT count(*) FROM navigation_connections c WHERE c.project_id = p.id)  AS connections,
       (SELECT count(*) FROM reconstruction_assets a WHERE a.project_id = p.id)   AS assets,
       (SELECT count(*) FROM detected_objects o WHERE o.project_id = p.id)        AS objects,
       (SELECT count(*) FROM measurement_records r WHERE r.project_id = p.id)     AS measurements,
       (SELECT count(*) FROM rooms rm WHERE rm.project_id = p.id)                 AS rooms
FROM projects p JOIN users u ON u.id = p.owner_id
ORDER BY u.email, p.created_at;

\echo === Row totals ===
SELECT 'projects' AS tbl, count(*) FROM projects
UNION ALL SELECT 'uploaded_media', count(*) FROM uploaded_media
UNION ALL SELECT 'processing_jobs', count(*) FROM processing_jobs
UNION ALL SELECT 'detected_objects', count(*) FROM detected_objects
UNION ALL SELECT 'measurement_records', count(*) FROM measurement_records
UNION ALL SELECT 'reconstruction_assets', count(*) FROM reconstruction_assets
UNION ALL SELECT 'navigation_nodes', count(*) FROM navigation_nodes
UNION ALL SELECT 'navigation_connections', count(*) FROM navigation_connections
UNION ALL SELECT 'rooms', count(*) FROM rooms;

\echo === Orphan check (should all be 0) ===
SELECT 'media without project' AS problem, count(*) FROM uploaded_media m WHERE NOT EXISTS (SELECT 1 FROM projects p WHERE p.id = m.project_id)
UNION ALL SELECT 'nodes without project', count(*) FROM navigation_nodes n WHERE NOT EXISTS (SELECT 1 FROM projects p WHERE p.id = n.project_id)
UNION ALL SELECT 'connections with missing node', count(*) FROM navigation_connections c
  WHERE NOT EXISTS (SELECT 1 FROM navigation_nodes n WHERE n.id = c.from_node_id) OR NOT EXISTS (SELECT 1 FROM navigation_nodes n WHERE n.id = c.to_node_id);
