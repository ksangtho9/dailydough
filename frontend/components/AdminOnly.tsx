"use client";

import { isAdminMode } from "@/lib/admin";

interface AdminOnlyProps {
  children: React.ReactNode;
}

/**
 * AdminOnly component - renders children only if admin mode is enabled.
 * 
 * Usage:
 *   <AdminOnly>
 *     <button>Admin Button</button>
 *   </AdminOnly>
 */
export function AdminOnly({ children }: AdminOnlyProps) {
  if (!isAdminMode()) {
    return null;
  }

  return <>{children}</>;
}


