"""
MistWANPerformance - Configuration Management

This module handles loading and validating configuration from environment variables
and configuration files.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from dotenv import load_dotenv


@dataclass
class MistConfig:
    """Configuration for Mist API connection."""
    api_token: str
    org_id: str
    api_host: str = "api.mist.com"


@dataclass
class SnowflakeConfig:
    """Configuration for Snowflake connection."""
    account: str
    user: str
    password: str
    database: str = "WAN_PERFORMANCE"
    schema: str = "RETAIL_WAN"
    warehouse: str = "COMPUTE_WH"
    role: Optional[str] = None


@dataclass
class ThresholdConfig:
    """Configuration for metric thresholds."""
    # Utilization thresholds (percentage)
    util_warn: float = 70.0
    util_high: float = 80.0
    util_critical: float = 90.0
    
    # Loss thresholds (percentage)
    loss_warn: float = 0.1
    loss_high: float = 0.5
    loss_critical: float = 1.0
    
    # Jitter thresholds (milliseconds)
    jitter_warn: float = 10.0
    jitter_high: float = 30.0
    jitter_critical: float = 50.0
    
    # Latency thresholds (milliseconds)
    latency_warn: float = 50.0
    latency_high: float = 100.0
    latency_critical: float = 150.0


@dataclass
class OperationalConfig:
    """Configuration for operational parameters."""
    page_limit: int = 1000
    rate_limit_delay: float = 0.1
    max_retries: int = 3
    retry_delay: float = 1.0


@dataclass
class Config:
    """
    Main configuration class that aggregates all configuration sections.
    
    Loads configuration from environment variables with .env file support.
    """
    mist: MistConfig = field(default_factory=lambda: None)
    snowflake: SnowflakeConfig = field(default_factory=lambda: None)
    thresholds: ThresholdConfig = field(default_factory=ThresholdConfig)
    operational: OperationalConfig = field(default_factory=OperationalConfig)
    
    # Threshold overrides by region/store type
    region_overrides: Dict[str, Dict[str, float]] = field(default_factory=dict)
    store_type_overrides: Dict[str, Dict[str, float]] = field(default_factory=dict)
    
    # Paths
    data_dir: Path = field(default_factory=lambda: Path("data"))
    log_dir: Path = field(default_factory=lambda: Path("data/logs"))
    cache_dir: Path = field(default_factory=lambda: Path("data/cache"))
    export_dir: Path = field(default_factory=lambda: Path("data/exports"))
    
    def __post_init__(self):
        """Load configuration from environment after initialization."""
        # Load .env file if it exists
        env_file = Path(".env")
        if env_file.exists():
            load_dotenv(env_file)
        
        # Load Mist configuration
        self.mist = MistConfig(
            api_token=self._get_required_env("MIST_API_TOKEN"),
            org_id=self._get_required_env("MIST_ORG_ID"),
            api_host=os.getenv("MIST_API_HOST", "api.mist.com")
        )
        
        # Load Snowflake configuration
        self.snowflake = SnowflakeConfig(
            account=self._get_required_env("SNF_ACCOUNT"),
            user=self._get_required_env("SNF_USER"),
            password=self._get_required_env("SNF_PASSWORD"),
            database=os.getenv("SNF_DATABASE", "WAN_PERFORMANCE"),
            schema=os.getenv("SNF_SCHEMA", "RETAIL_WAN"),
            warehouse=os.getenv("SNF_WAREHOUSE", "COMPUTE_WH"),
            role=os.getenv("SNF_ROLE")
        )
        
        # Load threshold configuration
        self.thresholds = ThresholdConfig(
            util_warn=float(os.getenv("UTIL_THRESHOLD_WARN", "70")),
            util_high=float(os.getenv("UTIL_THRESHOLD_HIGH", "80")),
            util_critical=float(os.getenv("UTIL_THRESHOLD_CRITICAL", "90")),
            loss_warn=float(os.getenv("LOSS_THRESHOLD_WARN", "0.1")),
            loss_high=float(os.getenv("LOSS_THRESHOLD_HIGH", "0.5")),
            loss_critical=float(os.getenv("LOSS_THRESHOLD_CRITICAL", "1.0")),
            jitter_warn=float(os.getenv("JITTER_THRESHOLD_WARN", "10")),
            jitter_high=float(os.getenv("JITTER_THRESHOLD_HIGH", "30")),
            jitter_critical=float(os.getenv("JITTER_THRESHOLD_CRITICAL", "50")),
            latency_warn=float(os.getenv("LATENCY_THRESHOLD_WARN", "50")),
            latency_high=float(os.getenv("LATENCY_THRESHOLD_HIGH", "100")),
            latency_critical=float(os.getenv("LATENCY_THRESHOLD_CRITICAL", "150"))
        )
        
        # Load operational configuration
        self.operational = OperationalConfig(
            page_limit=int(os.getenv("PAGE_LIMIT", "1000")),
            rate_limit_delay=float(os.getenv("RATE_LIMIT_DELAY", "0.1")),
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            retry_delay=float(os.getenv("RETRY_DELAY", "1.0"))
        )
        
        # Ensure data directories exist
        self._ensure_directories()
    
    def _get_required_env(self, key: str) -> str:
        """
        Get a required environment variable.
        
        Args:
            key: Environment variable name
        
        Returns:
            Environment variable value
        
        Raises:
            ValueError: If the environment variable is not set
        """
        value = os.getenv(key)
        if value is None:
            raise ValueError(f"Required environment variable {key} is not set")
        return value
    
    def _ensure_directories(self) -> None:
        """Create data directories if they don't exist."""
        for directory in [self.data_dir, self.log_dir, self.cache_dir, self.export_dir]:
            directory.mkdir(parents=True, exist_ok=True)
    
    def get_threshold_for_site(self, metric: str, level: str, 
                               region: Optional[str] = None, 
                               store_type: Optional[str] = None) -> float:
        """
        Get threshold value with support for region/store type overrides.
        
        Args:
            metric: Metric name ('util', 'loss', 'jitter', 'latency')
            level: Threshold level ('warn', 'high', 'critical')
            region: Optional region code for override lookup
            store_type: Optional store type for override lookup
        
        Returns:
            Threshold value (override if available, else default)
        """
        # Build attribute name
        attr_name = f"{metric}_{level}"
        
        # Check store type override first (higher priority)
        if store_type and store_type in self.store_type_overrides:
            overrides = self.store_type_overrides[store_type]
            if attr_name in overrides:
                return overrides[attr_name]
        
        # Check region override
        if region and region in self.region_overrides:
            overrides = self.region_overrides[region]
            if attr_name in overrides:
                return overrides[attr_name]
        
        # Return default threshold
        return getattr(self.thresholds, attr_name)
