import type { Metadata } from "next";
import { TryPage } from "@/components/try/TryPage";

export const metadata: Metadata = { title: "Bring your own vendor · CategoryOS" };

export default function Page() {
  return <TryPage />;
}
