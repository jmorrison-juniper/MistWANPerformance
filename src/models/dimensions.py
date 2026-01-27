"""
MistWANPerformance - Dimension Models

Data models for dimension tables in the data warehouse.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class DimSite:
    """
    Site dimension - represents a physical store/location.
    
    Primary Key: site_id (UUID from Mist API)
    """
    site_id: str
    site_name: str
    region: Optional[str] = None
    store_type: Optional[str] = None
    timezone: str = "UTC"
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> dict:
        """Convert to dictionary for database insertion."""
        return {
            "site_id": self.site_id,
            "site_name": self.site_name,
            "region": self.region,
            "store_type": self.store_type,
            "timezone": self.timezone,
            "address": self.address,
            "city": self.city,
            "state": self.state,
            "country": self.country,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }
    
    @classmethod
    def from_mist_site(cls, mist_site: dict) -> "DimSite":
        """
        Create DimSite from Mist API site response.
        
        Args:
            mist_site: Site dictionary from Mist API
        
        Returns:
            DimSite instance
        """
        # Extract location info
        location = mist_site.get("latlng", {}) or {}
        address_info = mist_site.get("address", "") or ""
        
        return cls(
            site_id=mist_site.get("id", ""),
            site_name=mist_site.get("name", "Unknown"),
            region=mist_site.get("sitegroup_ids", [None])[0] if mist_site.get("sitegroup_ids") else None,
            store_type=mist_site.get("notes", None),  # Often used for categorization
            timezone=mist_site.get("timezone", "UTC") or "UTC",
            address=address_info,
            city=mist_site.get("city"),
            state=mist_site.get("state"),
            country=mist_site.get("country_code"),
            latitude=location.get("lat"),
            longitude=location.get("lng")
        )


@dataclass
class DimCircuit:
    """
    Circuit dimension - represents a WAN circuit/interface.
    
    Primary Key: circuit_id (composite of device_id:port_name)
    """
    circuit_id: str
    site_id: str
    device_id: str
    port_name: str
    bandwidth_mbps: int = 1000
    role: str = "primary"  # primary, secondary, backup
    active_state: bool = True  # True if circuit is currently active/carrying traffic
    provider: Optional[str] = None
    circuit_type: Optional[str] = None  # MPLS, Internet, LTE, etc.
    ip_address: Optional[str] = None
    gateway: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> dict:
        """Convert to dictionary for database insertion."""
        return {
            "circuit_id": self.circuit_id,
            "site_id": self.site_id,
            "device_id": self.device_id,
            "port_name": self.port_name,
            "bandwidth_mbps": self.bandwidth_mbps,
            "role": self.role,
            "active_state": self.active_state,
            "provider": self.provider,
            "circuit_type": self.circuit_type,
            "ip_address": self.ip_address,
            "gateway": self.gateway,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }
    
    @classmethod
    def from_mist_device_port(
        cls, 
        site_id: str,
        device: dict, 
        port_name: str,
        port_data: dict
    ) -> "DimCircuit":
        """
        Create DimCircuit from Mist device and port data.
        
        Args:
            site_id: Site UUID
            device: Device dictionary from Mist API
            port_name: Port/interface name
            port_data: Port statistics dictionary
        
        Returns:
            DimCircuit instance
        """
        device_id = device.get("id", "")
        
        # Determine circuit role from port name or config
        role = "primary"
        port_lower = port_name.lower()
        if "backup" in port_lower or "lte" in port_lower:
            role = "backup"
        elif "secondary" in port_lower or "wan1" in port_lower:
            role = "secondary"
        elif "wan0" in port_lower:
            role = "primary"
        
        # Determine circuit type
        circuit_type = None
        if "lte" in port_lower:
            circuit_type = "LTE"
        elif "ge-" in port_lower or "eth" in port_lower:
            circuit_type = "Ethernet"
        
        # Determine active state from port status
        is_active = port_data.get("up", True)
        if role == "primary":
            is_active = True  # Primary is active unless explicitly down
        elif role in ("secondary", "backup"):
            is_active = port_data.get("is_active", False)
        
        return cls(
            circuit_id=f"{device_id}:{port_name}",
            site_id=site_id,
            device_id=device_id,
            port_name=port_name,
            bandwidth_mbps=port_data.get("speed", 1000),
            role=role,
            active_state=is_active,
            circuit_type=circuit_type,
            ip_address=port_data.get("ip"),
            gateway=port_data.get("gateway")
        )


@dataclass
class DimTime:
    """
    Time dimension - represents hourly time periods.
    
    Primary Key: hour_key (YYYYMMDDHH format)
    """
    hour_key: str  # YYYYMMDDHH format
    date_key: str  # YYYYMMDD format
    year: int
    month: int
    day: int
    hour: int
    day_of_week: int  # 0=Monday, 6=Sunday
    week_of_year: int
    is_weekend: bool
    is_business_hours: bool  # 8am-6pm local
    quarter: int
    
    def to_dict(self) -> dict:
        """Convert to dictionary for database insertion."""
        return {
            "hour_key": self.hour_key,
            "date_key": self.date_key,
            "year": self.year,
            "month": self.month,
            "day": self.day,
            "hour": self.hour,
            "day_of_week": self.day_of_week,
            "week_of_year": self.week_of_year,
            "is_weekend": self.is_weekend,
            "is_business_hours": self.is_business_hours,
            "quarter": self.quarter
        }
    
    @classmethod
    def from_datetime(cls, dt: datetime, local_tz_offset: int = 0) -> "DimTime":
        """
        Create DimTime from a datetime object.
        
        Args:
            dt: Datetime object (should be in UTC)
            local_tz_offset: Hours offset from UTC for business hours calculation
        
        Returns:
            DimTime instance
        """
        # Adjust for local timezone for business hours calculation
        local_hour = (dt.hour + local_tz_offset) % 24
        
        return cls(
            hour_key=dt.strftime("%Y%m%d%H"),
            date_key=dt.strftime("%Y%m%d"),
            year=dt.year,
            month=dt.month,
            day=dt.day,
            hour=dt.hour,
            day_of_week=dt.weekday(),
            week_of_year=dt.isocalendar()[1],
            is_weekend=dt.weekday() >= 5,
            is_business_hours=8 <= local_hour < 18,
            quarter=(dt.month - 1) // 3 + 1
        )
    
    @classmethod
    def generate_range(
        cls, 
        start_dt: datetime, 
        end_dt: datetime,
        local_tz_offset: int = 0
    ) -> list:
        """
        Generate DimTime records for a date range.
        
        Args:
            start_dt: Start datetime
            end_dt: End datetime
            local_tz_offset: Hours offset from UTC
        
        Returns:
            List of DimTime instances
        """
        from datetime import timedelta
        
        records = []
        current = start_dt.replace(minute=0, second=0, microsecond=0)
        
        while current <= end_dt:
            records.append(cls.from_datetime(current, local_tz_offset))
            current += timedelta(hours=1)
        
        return records
