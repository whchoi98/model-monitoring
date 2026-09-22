import AppShell from "@/components/AppShell";
import ModelExplorer from "@/components/ModelExplorer";

export const dynamic = "force-dynamic";

export default function ModelsPage() {
  return <AppShell navKey="models"><ModelExplorer /></AppShell>;
}
