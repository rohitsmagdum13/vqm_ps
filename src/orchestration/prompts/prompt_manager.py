"""Module: orchestration/prompts/prompt_manager.py

PromptManager for loading and rendering Jinja2 prompt templates.

All LLM prompts in VQMS are stored as versioned Jinja2 templates
in this directory. The PromptManager loads, caches, and renders
them with provided variables.

Usage:
    from orchestration.prompts.prompt_manager import PromptManager

    pm = PromptManager()
    rendered = pm.render("query_analysis_v1.j2", vendor_name="TechNova", ...)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import jinja2
import jinja2.meta
import structlog

logger = structlog.get_logger(__name__)

# Directory containing the .j2 template files
_TEMPLATES_DIR = Path(__file__).parent


class PromptManager:
    """Loads and renders versioned Jinja2 prompt templates.

    Templates are cached after first load to avoid repeated
    filesystem reads. Uses StrictUndefined so missing variables
    raise errors instead of rendering as empty strings.
    """

    def __init__(self) -> None:
        """Initialize the Jinja2 environment with file loader."""
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=False,
            undefined=jinja2.StrictUndefined,
            keep_trailing_newline=True,
        )
        # Cache for loaded Template objects
        self._cache: dict[str, jinja2.Template] = {}

    def render(self, template_name: str, **variables: Any) -> str:
        """Render a prompt template with the given variables.

        Args:
            template_name: Filename of the template (e.g., "query_analysis_v1.j2").
            **variables: Template variables to substitute.

        Returns:
            The rendered prompt string.

        Raises:
            jinja2.TemplateNotFound: If the template file doesn't exist.
            jinja2.UndefinedError: If a required variable is missing.
        """
        template = self._get_template(template_name)
        rendered = template.render(**variables)
        return rendered.strip()

    def get_metadata(self, template_name: str) -> dict:
        """Extract metadata from a template file.

        Returns template name, version (extracted from filename),
        and the list of undeclared variables the template expects.

        Args:
            template_name: Filename of the template.

        Returns:
            Dict with: template_name, version, required_variables.
        """
        # Extract version from filename pattern: name_vN.j2
        version_match = re.search(r"_v(\d+)\.j2$", template_name)
        version = version_match.group(1) if version_match else "unknown"

        # Find undeclared variables by parsing the template source
        source = self._env.loader.get_source(self._env, template_name)[0]
        parsed = self._env.parse(source)
        required_variables = sorted(jinja2.meta.find_undeclared_variables(parsed))

        return {
            "template_name": template_name,
            "version": version,
            "required_variables": required_variables,
        }

    def _get_template(self, template_name: str) -> jinja2.Template:
        """Load a template from cache or filesystem."""
        if template_name not in self._cache:
            self._cache[template_name] = self._env.get_template(template_name)
        return self._cache[template_name]
