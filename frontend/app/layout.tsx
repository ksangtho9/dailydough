// frontend/app/layout.tsx
import "./globals.css";
import type { Metadata } from "next";
import { ConditionalNav } from "@/components/ConditionalNav";
import { ConditionalMain } from "@/components/ConditionalMain";

export const metadata: Metadata = {
  title: "Bloom",
  description: "AI demand forecasting for bakeries",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-[#F8F1E8] text-slate-900">
        <ConditionalNav />
        <ConditionalMain>{children}</ConditionalMain>
      </body>
    </html>
  );
}
