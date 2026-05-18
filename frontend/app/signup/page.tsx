"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";
import { GlowingEffect } from "@/components/ui/glowing-effect";

export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }

    setLoading(true);

    try {
      const { data, error: authError } = await supabase.auth.signUp({
        email,
        password,
        options: {
          emailRedirectTo: `${window.location.origin}/auth/callback`,
        },
      });

      if (authError) {
        throw new Error(authError.message);
      }

      // If email confirmation is disabled, Supabase returns a session immediately
      if (data.session) {
        router.push("/dashboard");
        return;
      }

      // Email confirmation is enabled — show "check your email" state
      setSubmitted(true);
    } catch (err: any) {
      setError(err.message || "Signup failed. Please try again.");
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
          <h1 className="text-xl font-semibold tracking-tight text-slate-100">
            Create your account
          </h1>
          <p className="mt-1 text-sm text-slate-300">
            Start forecasting your bakery demand.
          </p>

          {submitted ? (
            <div className="mt-6 space-y-4">
              <div className="rounded-md bg-green-900/50 border border-green-700/50 px-4 py-4 text-sm text-green-200">
                <p className="font-medium">Check your email</p>
                <p className="mt-1 text-green-300">
                  We sent a confirmation link to{" "}
                  <span className="font-medium">{email}</span>. Click it to
                  activate your account.
                </p>
              </div>
              <p className="text-center text-xs text-slate-400">
                Already confirmed?{" "}
                <Link
                  href="/login"
                  className="text-amber-400 hover:text-amber-300"
                >
                  Sign in
                </Link>
              </p>
            </div>
          ) : (
            <>
              {error && (
                <p className="mt-3 rounded-md bg-red-900/50 border border-red-700/50 px-3 py-2 text-xs text-red-200">
                  {error}
                </p>
              )}

              <form onSubmit={handleSubmit} className="mt-6 space-y-4">
                <div>
                  <label className="block text-xs font-medium text-slate-200">
                    Email
                  </label>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
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
                    placeholder="Min. 8 characters"
                    required
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-200">
                    Confirm Password
                  </label>
                  <input
                    type="password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
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
                  {loading ? "Creating account..." : "Create account"}
                </button>
              </form>

              <p className="mt-4 text-center text-xs text-slate-400">
                Already have an account?{" "}
                <Link
                  href="/login"
                  className="text-amber-400 hover:text-amber-300"
                >
                  Sign in →
                </Link>
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
