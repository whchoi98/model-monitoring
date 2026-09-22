import AppShell from "@/components/AppShell";
import GptOnAwsPanel from "@/components/GptOnAwsPanel";

export const dynamic = "force-dynamic";

export default function GptOnAwsPage() {
  return <AppShell navKey="gptbench"><GptOnAwsPanel /></AppShell>;
}
