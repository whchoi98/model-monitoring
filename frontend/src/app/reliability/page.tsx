import AppShell from "@/components/AppShell";
import ReliabilityPanel from "@/components/ReliabilityPanel";

export const dynamic = "force-dynamic";

export default function ReliabilityPage() {
  return <AppShell navKey="reliability"><ReliabilityPanel /></AppShell>;
}
