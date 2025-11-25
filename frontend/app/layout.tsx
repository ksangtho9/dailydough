// frontend/app/layout.tsx
import "./globals.css";
import type { Metadata } from "next";
import { AppTopNav } from "@/components/AppTopNav";

export const metadata: Metadata = {
  title: "Daily Dough",
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
        <AppTopNav />
        <main className="mx-auto max-w-6xl px-6 pt-28 pb-10">{children}</main>
      </body>
    </html>
  );
}
