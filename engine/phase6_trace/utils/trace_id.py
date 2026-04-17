import uuid

def generate_trace_id(prefix: str = "trace") -> str:
    """
    Generate a unique trace ID using UUID4.
    Example: trace-123e4567-e89b-12d3-a456-426614174000
    """
    return f"{prefix}-{uuid.uuid4()}"
