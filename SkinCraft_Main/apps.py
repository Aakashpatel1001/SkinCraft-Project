from django.apps import AppConfig

class SkincraftMainConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'SkinCraft_Main'

    def ready(self):
        # If you have signals, import them here. 
        # Models are safe to import INSIDE this method if needed.
        try:
            import SkinCraft_Main.signals
        except ImportError:
            pass