"""Code validator for generated sample applications."""

from __future__ import annotations

import ast
import py_compile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.utils.logging import get_logger

logger = get_logger("generator.validator")


@dataclass
class ValidationResult:
    """Result of validating generated code."""

    valid: bool = True
    syntax_errors: list[str] = field(default_factory=list)
    import_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        """Check if there are any errors."""
        return len(self.syntax_errors) > 0 or len(self.import_errors) > 0


class CodeValidator:
    """
    Validates generated Python code.

    Performs:
    - Syntax validation (py_compile)
    - AST parsing validation
    - Import checking
    """

    def __init__(self) -> None:
        """Initialize the validator."""
        pass

    def validate(self, source_code: dict[str, str]) -> ValidationResult:
        """
        Validate all source files.

        Args:
            source_code: Dict mapping file paths to content

        Returns:
            ValidationResult with any errors found
        """
        result = ValidationResult()

        for file_path, content in source_code.items():
            if not file_path.endswith(".py"):
                continue

            # Validate syntax using py_compile first
            syntax_result = self._validate_syntax(file_path, content)
            if syntax_result:
                result.syntax_errors.append(syntax_result)
                result.valid = False
                # Skip AST validation if py_compile already found an error
                continue

            # Validate AST only if py_compile passed
            ast_result = self._validate_ast(file_path, content)
            if ast_result:
                result.syntax_errors.append(ast_result)
                result.valid = False
                continue

            # Check imports only if syntax is valid
            import_warnings = self._check_imports(file_path, content)
            result.warnings.extend(import_warnings)

        if result.valid:
            logger.debug("validation_passed", files=len(source_code))
        else:
            logger.warning(
                "validation_failed",
                syntax_errors=len(result.syntax_errors),
                import_errors=len(result.import_errors),
            )

        return result

    def _validate_syntax(self, file_path: str, content: str) -> Optional[str]:
        """
        Validate Python syntax using py_compile.

        Args:
            file_path: File path for error messages
            content: Python source code

        Returns:
            Error message or None if valid
        """
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
        ) as f:
            f.write(content)
            temp_path = f.name

        try:
            py_compile.compile(temp_path, doraise=True)
            return None
        except py_compile.PyCompileError as e:
            return f"{file_path}: {e}"
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def _validate_ast(self, file_path: str, content: str) -> Optional[str]:
        """
        Validate Python AST.

        Args:
            file_path: File path for error messages
            content: Python source code

        Returns:
            Error message or None if valid
        """
        try:
            ast.parse(content)
            return None
        except SyntaxError as e:
            return f"{file_path}:{e.lineno}: {e.msg}"

    def _check_imports(self, file_path: str, content: str) -> list[str]:
        """
        Check for potentially problematic imports.

        Args:
            file_path: File path for warnings
            content: Python source code

        Returns:
            List of warning messages
        """
        warnings = []

        try:
            tree = ast.parse(content)

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        warning = self._check_import_name(alias.name)
                        if warning:
                            warnings.append(f"{file_path}: {warning}")

                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        warning = self._check_import_name(node.module)
                        if warning:
                            warnings.append(f"{file_path}: {warning}")

        except SyntaxError:
            pass  # Already caught by syntax validation

        return warnings

    def _check_import_name(self, module_name: str) -> Optional[str]:
        """
        Check if an import is potentially problematic.

        Args:
            module_name: Module name to check

        Returns:
            Warning message or None
        """
        # Standard library modules that are always available
        stdlib_modules = {
            "os", "sys", "json", "time", "datetime", "logging",
            "typing", "dataclasses", "pathlib", "re", "asyncio",
            "functools", "collections", "itertools", "contextlib",
            "tempfile", "uuid", "hashlib", "base64",
        }

        # Expected third-party modules
        expected_modules = {
            "boto3", "botocore", "pytest", "httpx", "requests",
        }

        # Get top-level module
        top_module = module_name.split(".")[0]

        if top_module in stdlib_modules:
            return None

        if top_module in expected_modules:
            return None

        # Unknown module - might be missing from requirements
        return f"Import '{module_name}' may require adding to requirements"


def validate_all_files(
    source_code: dict[str, str],
    test_code: dict[str, str],
) -> ValidationResult:
    """
    Validate all generated files.

    Args:
        source_code: Source file contents
        test_code: Test file contents

    Returns:
        Combined ValidationResult
    """
    validator = CodeValidator()

    # Combine all files
    all_files = {**source_code, **test_code}

    return validator.validate(all_files)
