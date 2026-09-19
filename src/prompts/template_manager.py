from __future__ import annotations

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

log = logging.getLogger("hrcc.prompts")

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

_manager: TemplateManager | None = None


class TemplateManager:
    def __init__(self, template_dir: Path | str = _TEMPLATE_DIR) -> None:
        self._env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=False,
        )
        log.info("Jinja2 TemplateManager initialized from %s", template_dir)

    def render_template(self, template_name: str, **kwargs: object) -> str:
        if not template_name.endswith(".jinja"):
            template_name = f"{template_name}.jinja"
        try:
            template = self._env.get_template(template_name)
            return template.render(**kwargs).strip()
        except TemplateNotFound:
            log.error("Template not found: %s", template_name)
            raise
        except Exception:
            log.exception("Failed to render template: %s", template_name)
            raise

    def list_templates(self) -> list[str]:
        return sorted(self._env.list_templates(extensions=["jinja"]))


def get_template_manager() -> TemplateManager:
    global _manager
    if _manager is None:
        _manager = TemplateManager()
    return _manager
