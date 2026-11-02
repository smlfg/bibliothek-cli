import os

VARIABLES = (
    "BADTOOL_USER",
    "BADTOOL_PASSWORD",
    "BADTOOL_FIRSTNAME",
    "BADTOOL_LASTNAME",
    "BADTOOL_STATUS",
)


def load_credentials():
    return {name: os.environ.get(name, "") for name in VARIABLES}
