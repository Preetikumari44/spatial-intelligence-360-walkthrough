-- Deletes uploaded property data and everything generated from it. Keeps users, schema, migrations (flyway_schema_history).
-- Run through scripts\clean-demo-data.ps1 -Execute, which takes a pg_dump backup first.
-- Optional: keep specific projects with  psql -v keep="<uuid>,<uuid>"  (default: keep none).
\set ON_ERROR_STOP on
\if :{?keep}
\else
\set keep ''
\endif

BEGIN;
-- children first (the foreign keys also cascade, this just makes the order explicit and the counts visible)
CREATE TEMP TABLE _doomed ON COMMIT DROP AS
  SELECT id FROM projects WHERE id::text <> ALL (string_to_array(:'keep', ','));

DELETE FROM navigation_connections WHERE project_id IN (SELECT id FROM _doomed);
DELETE FROM navigation_nodes       WHERE project_id IN (SELECT id FROM _doomed);
DELETE FROM rooms                  WHERE project_id IN (SELECT id FROM _doomed);
DELETE FROM measurement_records    WHERE project_id IN (SELECT id FROM _doomed);
DELETE FROM detected_objects       WHERE project_id IN (SELECT id FROM _doomed);
DELETE FROM reconstruction_assets  WHERE project_id IN (SELECT id FROM _doomed);
DELETE FROM processing_jobs        WHERE project_id IN (SELECT id FROM _doomed);
DELETE FROM uploaded_media         WHERE project_id IN (SELECT id FROM _doomed);
DELETE FROM projects               WHERE id IN (SELECT id FROM _doomed);

-- leftovers that point at nothing (safe: a row with no parent can never be shown)
DELETE FROM navigation_connections c WHERE NOT EXISTS (SELECT 1 FROM navigation_nodes n WHERE n.id = c.from_node_id)
                                         OR NOT EXISTS (SELECT 1 FROM navigation_nodes n WHERE n.id = c.to_node_id);

-- refuse to commit if anything is still dangling
DO $$
DECLARE bad int;
BEGIN
  SELECT (SELECT count(*) FROM uploaded_media m WHERE NOT EXISTS (SELECT 1 FROM projects p WHERE p.id = m.project_id))
       + (SELECT count(*) FROM processing_jobs j WHERE NOT EXISTS (SELECT 1 FROM projects p WHERE p.id = j.project_id))
       + (SELECT count(*) FROM navigation_nodes n WHERE NOT EXISTS (SELECT 1 FROM projects p WHERE p.id = n.project_id))
    INTO bad;
  IF bad > 0 THEN RAISE EXCEPTION 'cleanup would leave % orphaned rows, rolled back', bad; END IF;
END $$;
COMMIT;
\echo Cleanup committed. Users and schema untouched.
