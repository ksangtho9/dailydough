"use client";

import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";

export function LogoutButton() {
  const router = useRouter();

  async function handleLogout() {
    await supabase.auth.signOut();
    router.push("/login");
  }

  return (
    <button
      onClick={handleLogout}
      className="w-full rounded-lg border px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-100"
    >
      Logout
    </button>
  );
}
