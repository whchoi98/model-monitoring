import AppShell from "@/components/AppShell";
import AnalysisPanel from "@/components/AnalysisPanel";

export const dynamic = "force-dynamic";

export default function AnalysisPage() {
  return <AppShell navKey="analysis"><AnalysisPanel /></AppShell>;
}
