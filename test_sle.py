from src.utils.config import Config
from src.api.mist_client import MistAPIClient
from src.dashboard.data_provider import DashboardDataProvider
config = Config()
client = MistAPIClient(config.mist, config.operational)
sle_data = client.get_org_sites_sle(sle="wan")
provider = DashboardDataProvider([], [])
provider.update_sle_data(sle_data)
degraded = provider.get_sle_degraded_sites()
print("Total sites:", len(sle_data.get("results", [])))
print("Degraded sites:", len(degraded))
for site in degraded[:5]:
    print("-", site)
