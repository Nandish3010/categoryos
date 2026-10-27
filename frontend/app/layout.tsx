import type { Metadata } from "next";
import { Suspense } from "react";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Tour } from "@/components/tour/Tour";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "CategoryOS",
  description:
    "Vendor onboarding decisions for pet-category buyers: verified numbers, live levers, one clear recommendation.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        {children}
        {/* the tour reads the pathname; outside a boundary that would make every route dynamic and fail prerendering */}
        <Suspense fallback={null}>
          <Tour />
        </Suspense>
      </body>
    </html>
  );
}
