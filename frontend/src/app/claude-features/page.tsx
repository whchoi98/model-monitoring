import AppShell from "@/components/AppShell";
import ClaudeFeaturesPanel from "@/components/ClaudeFeaturesPanel";

export const dynamic = "force-dynamic";

export default function ClaudeFeaturesPage() {
  return <AppShell navKey="features"><ClaudeFeaturesPanel /></AppShell>;
}
