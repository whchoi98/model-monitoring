import AppShell from "@/components/AppShell";
import EfficiencyPanel from "@/components/EfficiencyPanel";

export const dynamic = "force-dynamic";

export default function EfficiencyPage() {
  return <AppShell navKey="efficiency"><EfficiencyPanel /></AppShell>;
}
