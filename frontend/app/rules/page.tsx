import type { Metadata } from "next";
import { RulesPage } from "@/components/rules/RulesPage";

export const metadata: Metadata = { title: "Playbook · CategoryOS" };

export default function Page() {
  return <RulesPage />;
}
