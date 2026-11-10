-- Progress (0-100) and cooperative cancellation for processing jobs. Existing rows get progress 0 and are not cancelled.
ALTER TABLE processing_jobs ADD COLUMN progress INT NOT NULL DEFAULT 0;
ALTER TABLE processing_jobs ADD COLUMN cancel_requested BOOLEAN NOT NULL DEFAULT FALSE;
