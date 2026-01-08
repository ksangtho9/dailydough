"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { API_BASE_URL } from "@/lib/api";
import { GlowingEffect } from "@/components/ui/glowing-effect";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState(""); // email
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null); // 👈 new

  // 👇 check if we were logged out due to expiry
  useEffect(() => {
    if (typeof window === "undefined") return;
    const flag = window.localStorage.getItem("session_expired");
    if (flag) {
      setInfo("Your session expired. Please sign in again.");
      window.localStorage.removeItem("session_expired");
    }
  }, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setInfo(null);

    try {
      const body = new URLSearchParams();
      body.append("username", username);
      body.append("password", password);

      const res = await fetch(`${API_BASE_URL}/api/auth/token`, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body,
      });

      if (!res.ok) {
        const text = await res.text();
        throw new Error(`Login failed: ${text}`);
      }

      const data = await res.json(); // { access_token, token_type }
      if (typeof window !== "undefined") {
        localStorage.setItem("access_token", data.access_token);
        localStorage.removeItem("session_expired");
      }

      router.push("/dashboard");
    } catch (err: any) {
      console.error(err);
      setError(err.message || "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="relative w-full max-w-md rounded-2xl border-[0.75px] border-slate-700 bg-slate-800 p-6 shadow-lg">
        <GlowingEffect
          spread={40}
          glow={true}
          disabled={false}
          proximity={64}
          inactiveZone={0.01}
          borderWidth={3}
        />
        <div className="relative">
          <h1 className="text-xl font-semibold tracking-tight text-slate-100">Bloom</h1>
          <p className="mt-1 text-sm text-slate-300">
            Sign in to view products and forecasts.
          </p>

          {info && (
            <p className="mt-3 rounded-md bg-blue-900/50 border border-blue-700/50 px-3 py-2 text-xs text-blue-200">
              {info}
            </p>
          )}

          {error && (
            <p className="mt-3 rounded-md bg-red-900/50 border border-red-700/50 px-3 py-2 text-xs text-red-200">
              {error}
            </p>
          )}

          <form onSubmit={handleSubmit} className="mt-6 space-y-4">
            <div>
              <label className="block text-xs font-medium text-slate-200">
                Username / Email
              </label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-700 px-3 py-2 text-sm text-white placeholder:text-slate-400 outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-500/20"
                placeholder="you@example.com"
                required
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-200">
                Password
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-700 px-3 py-2 text-sm text-white placeholder:text-slate-400 outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-500/20"
                placeholder="••••••••"
                required
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="mt-2 w-full rounded-lg bg-amber-600 px-3 py-2 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? "Signing in..." : "Sign in"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

