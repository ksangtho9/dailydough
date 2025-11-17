"use client";

import { useRouter } from "next/navigation";

export function LogoutButton() {
  const router = useRouter();

  function handleLogout() {
    if (typeof window !== "undefined") {
      localStorage.removeItem("access_token");
    }
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
