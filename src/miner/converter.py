"""CloudFormation to Terraform conversion using cf2tf."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Optional

from src.utils.logging import get_logger

logger = get_logger("miner.converter")


class ConversionError(Exception):
    """Error during template conversion."""

    pass


class CloudFormationConverter:
    """
    Converts CloudFormation templates to Terraform using cf2tf.

    cf2tf is a tool that converts CloudFormation templates to Terraform.
    https://github.com/DontShaveTheYak/cf2tf
    """

    def __init__(self, cache_dir: Optional[Path] = None) -> None:
        """
        Initialize the converter.

        Args:
            cache_dir: Directory for temporary conversion files
        """
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._cf2tf_available: Optional[bool] = None

    async def is_available(self) -> bool:
        """
        Check if cf2tf is available.

        Returns:
            True if cf2tf is installed
        """
        if self._cf2tf_available is not None:
            return self._cf2tf_available

        try:
            process = await asyncio.create_subprocess_exec(
                "cf2tf", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await process.communicate()
            self._cf2tf_available = process.returncode == 0
        except FileNotFoundError:
            self._cf2tf_available = False

        return self._cf2tf_available

    async def convert(
        self,
        cloudformation_content: str,
        template_id: str = "template",
    ) -> str:
        """
        Convert CloudFormation template to Terraform.

        Args:
            cloudformation_content: CloudFormation template content (YAML or JSON)
            template_id: Identifier for the template

        Returns:
            Terraform HCL content

        Raises:
            ConversionError: If conversion fails
        """
        if not await self.is_available():
            raise ConversionError("cf2tf is not installed")

        # Determine format (YAML or JSON)
        is_json = self._is_json(cloudformation_content)

        # Create temporary file for input
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Write input file
            input_ext = ".json" if is_json else ".yaml"
            input_file = temp_path / f"template{input_ext}"
            input_file.write_text(cloudformation_content)

            # Output directory
            output_dir = temp_path / "output"
            output_dir.mkdir()

            # Run cf2tf
            try:
                process = await asyncio.create_subprocess_exec(
                    "cf2tf", str(input_file), "-o", str(output_dir),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await process.communicate()

                if process.returncode != 0:
                    error_msg = stderr.decode() if stderr else "Unknown error"
                    raise ConversionError(f"cf2tf failed: {error_msg}")

                # Read output
                main_tf = output_dir / "main.tf"
                if main_tf.exists():
                    return main_tf.read_text()

                # Check for other .tf files
                tf_files = list(output_dir.glob("*.tf"))
                if tf_files:
                    return tf_files[0].read_text()

                raise ConversionError("No Terraform output generated")

            except Exception as e:
                if isinstance(e, ConversionError):
                    raise
                raise ConversionError(f"Conversion failed: {e}") from e

    async def convert_serverless(
        self,
        serverless_content: str,
        template_id: str = "template",
    ) -> str:
        """
        Convert Serverless Framework config to Terraform.

        This is a simplified conversion that extracts the key resources.

        Args:
            serverless_content: serverless.yml content
            template_id: Identifier for the template

        Returns:
            Terraform HCL content
        """
        import yaml

        try:
            config = yaml.safe_load(serverless_content)
        except yaml.YAMLError as e:
            raise ConversionError(f"Invalid YAML: {e}") from e

        # Generate Terraform from Serverless config
        terraform_parts = []

        # Provider
        terraform_parts.append(self._generate_provider())

        # Functions -> Lambda resources
        functions = config.get("functions", {})
        for func_name, func_config in functions.items():
            terraform_parts.append(
                self._generate_lambda_resource(func_name, func_config)
            )

        # Resources -> Direct CloudFormation resources
        resources = config.get("resources", {})
        if resources:
            # For now, note that CloudFormation resources exist
            terraform_parts.append(
                f"# Additional CloudFormation resources defined in serverless.yml\n"
                f"# These would need manual conversion or cf2tf\n"
            )

        return "\n\n".join(terraform_parts)

    @staticmethod
    def _is_json(content: str) -> bool:
        """Check if content is JSON."""
        try:
            json.loads(content)
            return True
        except json.JSONDecodeError:
            return False

    @staticmethod
    def _generate_provider() -> str:
        """Generate AWS provider block."""
        return '''provider "aws" {
  # LocalStack endpoint configuration
  endpoints {
    apigateway     = "http://localhost:4566"
    cloudwatch     = "http://localhost:4566"
    dynamodb       = "http://localhost:4566"
    iam            = "http://localhost:4566"
    lambda         = "http://localhost:4566"
    s3             = "http://localhost:4566"
    sns            = "http://localhost:4566"
    sqs            = "http://localhost:4566"
    stepfunctions  = "http://localhost:4566"
  }

  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true

  access_key = "test"
  secret_key = "test"
  region     = "us-east-1"
}'''

    @staticmethod
    def _generate_lambda_resource(func_name: str, func_config: dict) -> str:
        """Generate Lambda resource from Serverless function config."""
        handler = func_config.get("handler", "handler.handler")
        runtime = func_config.get("runtime", "python3.9")
        memory = func_config.get("memorySize", 128)
        timeout = func_config.get("timeout", 6)

        # Sanitize function name for Terraform
        tf_name = func_name.replace("-", "_").replace(".", "_")

        return f'''resource "aws_lambda_function" "{tf_name}" {{
  function_name = "{func_name}"
  handler       = "{handler}"
  runtime       = "{runtime}"
  memory_size   = {memory}
  timeout       = {timeout}
  role          = aws_iam_role.lambda_exec.arn

  # Placeholder for deployment package
  filename      = "lambda.zip"
}}

resource "aws_iam_role" "lambda_exec" {{
  name = "{func_name}-role"

  assume_role_policy = jsonencode({{
    Version = "2012-10-17"
    Statement = [{{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {{
        Service = "lambda.amazonaws.com"
      }}
    }}]
  }})
}}'''
