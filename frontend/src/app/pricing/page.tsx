import AppShell from "@/components/AppShell";
import PricingPanel from "@/components/PricingPanel";

export const dynamic = "force-dynamic";

export default function PricingPage() {
  return <AppShell navKey="pricing"><PricingPanel /></AppShell>;
}
