"use client";

import { useState, useEffect } from "react";
import { refreshAdminStatus, isAdminMode } from "@/lib/admin";

interface AdminOnlyProps {
  children: React.ReactNode;
}

export function AdminOnly({ children }: AdminOnlyProps) {
  const [isAdmin, setIsAdmin] = useState(isAdminMode());

  useEffect(() => {
    refreshAdminStatus().then(setIsAdmin);
  }, []);

  if (!isAdmin) return null;
  return <>{children}</>;
}
