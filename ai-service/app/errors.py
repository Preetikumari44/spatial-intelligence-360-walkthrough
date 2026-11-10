class PipelineError(Exception):
    """A failure the caller should see verbatim. 4xx means bad input, 5xx means the pipeline itself broke."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


class Cancelled(PipelineError):
    """The user cancelled the job. The Java side maps HTTP 499 to the CANCELLED job status."""

    def __init__(self, message: str = "Cancelled by the user"):
        super().__init__(message, 499)
