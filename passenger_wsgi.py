import os
import sys

PROJECT_ROOT = os.path.realpath(os.path.dirname(__file__))
if PROJECT_ROOT in sys.path:
    sys.path.remove(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("DJANGO_DEBUG", "0")

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
