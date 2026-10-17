from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        # Register user-created membership persistence; no implicit PRO grants.
        from . import signals  # noqa: F401
