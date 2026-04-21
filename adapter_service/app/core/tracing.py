from itertools import count
from time import strftime


_TRACE_COUNTER = count(1)


def new_trace_id(prefix: str) -> str:
    return "{0}-{1}-{2:04d}".format(prefix, strftime("%Y%m%d%H%M%S"), next(_TRACE_COUNTER))

