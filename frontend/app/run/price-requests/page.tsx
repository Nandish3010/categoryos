import type { Metadata } from "next";
import { PriceRequestsPage } from "@/components/run/PriceRequestsPage";

export const metadata: Metadata = { title: "Price requests · CategoryOS" };

export default function Page() {
  return <PriceRequestsPage />;
}
