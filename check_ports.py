"""Quick script to analyze port data in Redis."""
import json
import os

# Read temp file
temp_path = os.path.join(os.environ.get('TEMP', '/tmp'), 'ports.json')
with open(temp_path, 'r') as f:
    ports = json.load(f)

# Filter WAN ports on gateway devices
wan_ports = [p for p in ports if p.get('device_type') == 'gateway' and p.get('port_usage') == 'wan']

print(f"Total WAN ports: {len(wan_ports)}")
print("\nWAN Port Status:")
for port in wan_ports:
    print(f"  {port.get('port_id')}: up={port.get('up')}, disabled={port.get('disabled')}")

# Count disconnected gateways
gateway_ports = [p for p in ports if p.get('device_type') == 'gateway']
gateway_macs = set(p.get('mac') for p in gateway_ports)
print(f"\nGateway devices found: {len(gateway_macs)}")

# Check for disabled/down ports
down_ports = [p for p in wan_ports if not p.get('up', True)]
disabled_ports = [p for p in wan_ports if p.get('disabled', False)]

print(f"\nWAN ports that are DOWN (up=False): {len(down_ports)}")
for p in down_ports:
    print(f"  {p.get('port_id')}: up={p.get('up')}")

print(f"\nWAN ports that are DISABLED (disabled=True): {len(disabled_ports)}")
for p in disabled_ports:
    print(f"  {p.get('port_id')}: disabled={p.get('disabled')}")

# Check all port types on gateways
print("\n\nAll gateway port types:")
gateway_usages = {}
for p in gateway_ports:
    usage = p.get('port_usage', 'NONE')
    up = p.get('up', True)
    disabled = p.get('disabled', False)
    key = f"{usage} (up={up}, disabled={disabled})"
    gateway_usages[key] = gateway_usages.get(key, 0) + 1
    
for usage, count in sorted(gateway_usages.items()):
    print(f"  {usage}: {count}")
