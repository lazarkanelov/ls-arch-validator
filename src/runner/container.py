"""LocalStack container lifecycle management."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Optional

from src.utils.logging import get_logger

logger = get_logger("runner.container")

# Container resource limits
CONTAINER_LIMITS = {
    "mem_limit": "2g",
    "cpu_period": 100000,
    "cpu_quota": 100000,  # 1 CPU
}

# Default LocalStack image
DEFAULT_IMAGE = "localstack/localstack:latest"

# Health check settings
HEALTH_CHECK_INTERVAL = 2  # seconds
HEALTH_CHECK_TIMEOUT = 60  # seconds


@dataclass
class ContainerInfo:
    """Information about a running LocalStack container."""

    container_id: str
    name: str
    port: int
    image: str
    status: str = "created"
    endpoint_url: str = ""

    def __post_init__(self) -> None:
        if not self.endpoint_url:
            self.endpoint_url = f"http://localhost:{self.port}"


@dataclass
class ContainerConfig:
    """Configuration for LocalStack container."""

    image: str = DEFAULT_IMAGE
    port: int = 4566
    name_prefix: str = "ls-validator"
    environment: dict[str, str] = field(default_factory=dict)
    mem_limit: str = "2g"
    cpu_count: float = 1.0

    def __post_init__(self) -> None:
        # Add default environment variables
        default_env = {
            "DEBUG": "0",
            "PERSISTENCE": "0",
            "EAGER_SERVICE_LOADING": "1",
        }
        for key, value in default_env.items():
            if key not in self.environment:
                self.environment[key] = value


class ContainerManager:
    """
    Manages LocalStack container lifecycle.

    Handles starting, health checking, and stopping containers
    for validation runs.
    """

    def __init__(self, config: Optional[ContainerConfig] = None) -> None:
        """
        Initialize the container manager.

        Args:
            config: Container configuration
        """
        self.config = config or ContainerConfig()
        self._docker_client = None
        self._containers: dict[str, ContainerInfo] = {}

    def _get_docker_client(self):
        """Get or create Docker client."""
        if self._docker_client is None:
            import docker
            self._docker_client = docker.from_env()
        return self._docker_client

    async def start_container(
        self,
        instance_id: str,
        port: Optional[int] = None,
    ) -> ContainerInfo:
        """
        Start a new LocalStack container.

        Uses Docker's automatic port assignment when port is not specified
        to avoid race conditions between port checking and container startup.

        Args:
            instance_id: Unique identifier for this instance
            port: Port to expose (Docker auto-assigns if not specified)

        Returns:
            ContainerInfo for the started container
        """
        client = self._get_docker_client()

        # Generate container name
        container_name = f"{self.config.name_prefix}-{instance_id}"

        # Use Docker's automatic port assignment if port not specified
        # This eliminates the race condition between find_available_port() and run()
        port_binding = port if port is not None else None

        logger.info(
            "starting_container",
            name=container_name,
            image=self.config.image,
            port=port_binding or "auto",
        )

        try:
            # Pull image if not present
            try:
                client.images.get(self.config.image)
            except Exception:
                logger.info("pulling_image", image=self.config.image)
                client.images.pull(self.config.image)

            # Start container with Docker-assigned port if not specified
            container = client.containers.run(
                self.config.image,
                name=container_name,
                detach=True,
                ports={"4566/tcp": port_binding},  # None = Docker assigns port
                environment=self.config.environment,
                mem_limit=self.config.mem_limit,
                cpu_count=self.config.cpu_count,
                remove=True,  # Auto-remove when stopped
            )

            # Get the actual assigned port from container metadata
            container.reload()  # Refresh container data
            port_info = container.attrs.get("NetworkSettings", {}).get("Ports", {})
            assigned_port = port_binding

            if not assigned_port:
                # Extract Docker-assigned port
                port_mappings = port_info.get("4566/tcp", [])
                if port_mappings:
                    assigned_port = int(port_mappings[0].get("HostPort", self.config.port))
                else:
                    assigned_port = self.config.port

            info = ContainerInfo(
                container_id=container.id,
                name=container_name,
                port=assigned_port,
                image=self.config.image,
                status="starting",
            )

            self._containers[instance_id] = info

            logger.debug(
                "container_port_assigned",
                name=container_name,
                requested_port=port_binding or "auto",
                assigned_port=assigned_port,
            )

            # Wait for container to be healthy
            await self._wait_for_healthy(info)

            info.status = "running"
            logger.info(
                "container_started",
                name=container_name,
                port=assigned_port,
                endpoint=info.endpoint_url,
            )

            return info

        except Exception as e:
            logger.error(
                "container_start_failed",
                name=container_name,
                error=str(e),
            )
            raise

    async def stop_container(self, instance_id: str) -> None:
        """
        Stop and remove a container.

        Args:
            instance_id: Instance identifier
        """
        if instance_id not in self._containers:
            return

        info = self._containers[instance_id]
        client = self._get_docker_client()

        try:
            container = client.containers.get(info.container_id)
            container.stop(timeout=10)
            logger.info("container_stopped", name=info.name)
        except Exception as e:
            logger.warning("container_stop_error", name=info.name, error=str(e))
        finally:
            del self._containers[instance_id]

    async def cleanup_all(self) -> None:
        """Stop and remove all managed containers."""
        instance_ids = list(self._containers.keys())
        for instance_id in instance_ids:
            await self.stop_container(instance_id)

    def get_container(self, instance_id: str) -> Optional[ContainerInfo]:
        """Get container info by instance ID."""
        return self._containers.get(instance_id)

    def get_endpoint_url(self, instance_id: str) -> Optional[str]:
        """Get the endpoint URL for a container."""
        info = self._containers.get(instance_id)
        return info.endpoint_url if info else None

    async def _wait_for_healthy(self, info: ContainerInfo) -> None:
        """
        Wait for container to be healthy.

        Args:
            info: Container info

        Raises:
            TimeoutError: If container doesn't become healthy
        """
        import httpx

        health_url = f"{info.endpoint_url}/_localstack/health"
        start_time = asyncio.get_event_loop().time()

        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > HEALTH_CHECK_TIMEOUT:
                raise TimeoutError(
                    f"Container {info.name} did not become healthy within {HEALTH_CHECK_TIMEOUT}s"
                )

            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(health_url, timeout=5.0)
                    if response.status_code == 200:
                        logger.debug("container_healthy", name=info.name)
                        return
            except Exception:
                pass

            await asyncio.sleep(HEALTH_CHECK_INTERVAL)

    def _find_available_port(self) -> int:
        """Find an available port for the container."""
        import socket

        # Start from base port and find available
        base_port = self.config.port
        used_ports = {c.port for c in self._containers.values()}

        for offset in range(100):
            port = base_port + offset
            if port in used_ports:
                continue

            # Check if port is actually available
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(("localhost", port))
                    return port
            except OSError:
                continue

        raise RuntimeError("No available ports found")

    async def get_logs(self, instance_id: str, tail: int = 100) -> str:
        """
        Get container logs.

        Args:
            instance_id: Instance identifier
            tail: Number of lines to return

        Returns:
            Container logs
        """
        if instance_id not in self._containers:
            return ""

        info = self._containers[instance_id]
        client = self._get_docker_client()

        try:
            container = client.containers.get(info.container_id)
            logs = container.logs(tail=tail, timestamps=True)
            return logs.decode("utf-8")
        except Exception as e:
            logger.warning("logs_fetch_error", name=info.name, error=str(e))
            return ""
