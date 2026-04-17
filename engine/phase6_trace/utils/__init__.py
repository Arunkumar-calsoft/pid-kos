# Make utils a package
from .trace_id import generate_trace_id
from .time import current_utc_time

__all__ = ["generate_trace_id", "current_utc_time"]
