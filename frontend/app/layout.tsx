// frontend/app/layout.tsx
import "./globals.css";
import type { Metadata } from "next";
import { Sidebar } from "@/components/Sidebar";

export const metadata: Metadata = {
  title: "BAKEZY Dashboard",
  description: "AI demand forecasting for bakeries",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-[#fdf7f2] text-slate-900">
        <div className="flex min-h-screen">
          {/* Sidebar */}
          <Sidebar />

          {/* Main content area */}
          <main className="flex-1">
            <div className="mx-auto max-w-6xl px-6 py-6">{children}</div>
          </main>
        </div>
      </body>
    </html>
  );
}
