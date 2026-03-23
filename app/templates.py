from fastapi.templating import Jinja2Templates

from app.config import Settings


class TemplateProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.templates = Jinja2Templates(directory=str(settings.templates_dir))

    def renderer(self) -> Jinja2Templates:
        return self.templates