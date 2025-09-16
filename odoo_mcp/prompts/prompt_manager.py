"""
Prompt Manager implementation for Odoo MCP Server.
This module provides prompt management and template handling functionality.
"""

import logging
import json
from typing import Dict, Any, Optional, List
from pathlib import Path

from odoo_mcp.error_handling.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

# Global prompt manager instance
_prompt_manager = None


def initialize_prompt_manager(config: Dict[str, Any]) -> None:
    """
    Initialize the global prompt manager.

    Args:
        config: Configuration dictionary

    Raises:
        ConfigurationError: If the prompt manager is already initialized
    """
    global _prompt_manager
    if _prompt_manager is not None:
        raise ConfigurationError("Prompt manager is already initialized")

    _prompt_manager = PromptManager(config)
    logger.info("Prompt manager initialized successfully")


def get_prompt_manager() -> "PromptManager":
    """
    Get the global prompt manager instance.

    Returns:
        PromptManager: The global prompt manager instance

    Raises:
        ConfigurationError: If the prompt manager is not initialized
    """
    if _prompt_manager is None:
        raise ConfigurationError("Prompt manager is not initialized")
    return _prompt_manager


class PromptManager:
    """Manages system prompts and templates."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the prompt manager.

        Args:
            config: Configuration dictionary containing prompt settings
        """
        self.config = config
        self.prompts_dir = Path(config.get("prompts_dir", "prompts"))
        self.templates_dir = self.prompts_dir / "templates"
        self.prompts: Dict[str, str] = {}
        self.templates: Dict[str, str] = {}

        # Create directories if they don't exist
        self.prompts_dir.mkdir(parents=True, exist_ok=True)
        self.templates_dir.mkdir(parents=True, exist_ok=True)

        # Load prompts and templates
        self._load_prompts()
        self._load_templates()

    def _load_prompts(self) -> None:
        """Load all prompt files from the prompts directory."""
        try:
            for prompt_file in self.prompts_dir.glob("*.json"):
                with open(prompt_file, "r", encoding="utf-8") as f:
                    prompt_data = json.load(f)
                    prompt_name = prompt_file.stem
                    self.prompts[prompt_name] = prompt_data.get("content", "")
                    logger.debug(f"Loaded prompt: {prompt_name}")
        except Exception as e:
            logger.error(f"Error loading prompts: {str(e)}")
            raise

    def _load_templates(self) -> None:
        """Load all template files from the templates directory."""
        try:
            for template_file in self.templates_dir.glob("*.json"):
                with open(template_file, "r", encoding="utf-8") as f:
                    template_data = json.load(f)
                    template_name = template_file.stem
                    self.templates[template_name] = template_data.get("content", "")
                    logger.debug(f"Loaded template: {template_name}")
        except Exception as e:
            logger.error(f"Error loading templates: {str(e)}")
            raise

    def get_prompt(self, prompt_name: str) -> Optional[str]:
        """
        Get a prompt by name.

        Args:
            prompt_name: Name of the prompt to retrieve

        Returns:
            Optional[str]: The prompt content if found, None otherwise
        """
        return self.prompts.get(prompt_name)

    def get_template(self, template_name: str) -> Optional[str]:
        """
        Get a template by name.

        Args:
            template_name: Name of the template to retrieve

        Returns:
            Optional[str]: The template content if found, None otherwise
        """
        return self.templates.get(template_name)

    def format_template(self, template_name: str, **kwargs) -> Optional[str]:
        """
        Format a template with the provided variables.

        Args:
            template_name: Name of the template to format
            **kwargs: Variables to use in template formatting

        Returns:
            Optional[str]: The formatted template if found, None otherwise
        """
        template = self.get_template(template_name)
        if template:
            try:
                return template.format(**kwargs)
            except KeyError as e:
                logger.error(f"Missing template variable: {str(e)}")
                return None
        return None

    def add_prompt(self, prompt_name: str, content: str) -> bool:
        """
        Add a new prompt.

        Args:
            prompt_name: Name of the prompt
            content: Content of the prompt

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            prompt_file = self.prompts_dir / f"{prompt_name}.json"
            with open(prompt_file, "w", encoding="utf-8") as f:
                json.dump({"content": content}, f, indent=2)
            self.prompts[prompt_name] = content
            logger.info(f"Added prompt: {prompt_name}")
            return True
        except Exception as e:
            logger.error(f"Error adding prompt: {str(e)}")
            return False

    def add_template(self, template_name: str, content: str) -> bool:
        """
        Add a new template.

        Args:
            template_name: Name of the template
            content: Content of the template

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            template_file = self.templates_dir / f"{template_name}.json"
            with open(template_file, "w", encoding="utf-8") as f:
                json.dump({"content": content}, f, indent=2)
            self.templates[template_name] = content
            logger.info(f"Added template: {template_name}")
            return True
        except Exception as e:
            logger.error(f"Error adding template: {str(e)}")
            return False

    def remove_prompt(self, prompt_name: str) -> bool:
        """
        Remove a prompt.

        Args:
            prompt_name: Name of the prompt to remove

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            prompt_file = self.prompts_dir / f"{prompt_name}.json"
            if prompt_file.exists():
                prompt_file.unlink()
                del self.prompts[prompt_name]
                logger.info(f"Removed prompt: {prompt_name}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error removing prompt: {str(e)}")
            return False

    def remove_template(self, template_name: str) -> bool:
        """
        Remove a template.

        Args:
            template_name: Name of the template to remove

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            template_file = self.templates_dir / f"{template_name}.json"
            if template_file.exists():
                template_file.unlink()
                del self.templates[template_name]
                logger.info(f"Removed template: {template_name}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error removing template: {str(e)}")
            return False

    def list_prompts(self) -> List[str]:
        """
        List all available prompts.

        Returns:
            List[str]: List of prompt names
        """
        return list(self.prompts.keys())

    def list_templates(self) -> List[str]:
        """
        List all available templates.

        Returns:
            List[str]: List of template names
        """
        return list(self.templates.keys())
