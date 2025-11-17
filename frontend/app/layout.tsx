import { LogoutButton } from "@/components/LogoutButton";
import type { Metadata } from "next";
import "./globals.css";
import Link from "next/link";

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
      <body className="min-h-screen bg-slate-50 text-slate-900">
        <div className="flex min-h-screen">
          {/* Sidebar */}
          <aside className="w-64 border-r bg-white shadow-sm flex flex-col">
            <div className="px-6 py-4 border-b">
              <h1 className="text-xl font-bold tracking-tight">BAKEZY</h1>
              <p className="text-xs text-slate-500">
                Bakery demand forecasting
              </p>
            </div>

            <nav className="px-4 py-4 space-y-2 text-sm flex-1">
              <Link
                href="/products"
                className="block rounded-lg px-3 py-2 hover:bg-slate-100"
              >
                Products
                </Link>

                <Link
                  href="/upload"
                  className="block rounded-lg px-3 py-2 hover:bg-slate-100"
                >
                  Upload sales CSV
                </Link>
              </nav>

            <div className="px-4 py-4 border-t">
              <LogoutButton />
            </div>
          </aside>


          {/* Main content */}
          <main className="flex-1 px-8 py-6">{children}</main>
        </div>
      </body>
    </html>
  );
}
