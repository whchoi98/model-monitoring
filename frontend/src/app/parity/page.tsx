import AppShell from "@/components/AppShell";
import ParityPanel from "@/components/ParityPanel";

export const dynamic = "force-dynamic";

export default function ParityPage() {
  return <AppShell navKey="parity"><ParityPanel /></AppShell>;
}
