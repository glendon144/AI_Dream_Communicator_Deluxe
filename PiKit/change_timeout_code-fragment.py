import os

CONNECT_TIMEOUT = float(os.getenv("PIKIT_CONNECT_TIMEOUT", "10"))
READ_TIMEOUT    = float(os.getenv("PIKIT_READ_TIMEOUT", "600"))

