import AppShell from "@/components/AppShell";
import CostDashboardPanel from "@/components/CostDashboardPanel";

export const dynamic = "force-dynamic";

export default function CostPage() {
  return <AppShell navKey="cost"><CostDashboardPanel /></AppShell>;
}
