"""Feature-grouped API endpoint registrations."""

from . import common
from . import core, study, documents, reference, search, store, workspace, personal, sync

route = common.route
ROUTES = common.ROUTES
FILE_ROUTES = common.FILE_ROUTES
CSRF_TOKEN = common.CSRF_TOKEN
CSRF_HEADER = common.CSRF_HEADER
VERSION = common.VERSION
_ai_context = core._ai_context
