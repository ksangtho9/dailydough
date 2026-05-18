"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { supabase } from "@/lib/supabase";
import { TextShimmer } from "@/components/ui/text-shimmer";

export default function AuthCallbackPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const tokenHash = searchParams.get("token_hash");
    const type = searchParams.get("type");

    if (tokenHash && type) {
      supabase.auth
        .verifyOtp({ token_hash: tokenHash, type: type as any })
        .then(({ error }) => {
          if (error) {
            router.push("/login?error=confirmation_failed");
          } else {
            router.push("/dashboard");
          }
        });
    } else {
      // Fallback: check if a session already exists (e.g. magic link auto-handled by client)
      supabase.auth.getSession().then(({ data: { session } }) => {
        if (session) {
          router.push("/dashboard");
        } else {
          router.push("/login");
        }
      });
    }
  }, [router, searchParams]);

  return (
    <div className="flex min-h-screen items-center justify-center">
      <TextShimmer className="text-sm text-slate-500" duration={1.5}>
        Confirming your account…
      </TextShimmer>
    </div>
  );
}
