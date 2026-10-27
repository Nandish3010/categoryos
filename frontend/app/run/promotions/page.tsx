import type { Metadata } from "next";
import { PromotionsPage } from "@/components/run/PromotionsPage";

export const metadata: Metadata = { title: "Promotions · CategoryOS" };

export default function Page() {
  return <PromotionsPage />;
}
