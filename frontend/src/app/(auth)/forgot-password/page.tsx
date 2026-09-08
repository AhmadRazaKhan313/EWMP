"use client";

import { useState } from "react";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Loader2, Shield, ArrowLeft, Mail } from "lucide-react";
import { authService } from "@/services/auth.service";
import { cn } from "@/utils/cn";

const schema = z.object({ email: z.string().email("Enter a valid email address") });
type FormData = z.infer<typeof schema>;

export default function ForgotPasswordPage() {
  const [isLoading, setIsLoading] = useState(false);
  const [sent, setSent] = useState(false);

  const { register, handleSubmit, formState: { errors } } = useForm<FormData>({
    resolver: zodResolver(schema),
  });

  async function onSubmit(values: FormData) {
    setIsLoading(true);
    try {
      await authService.forgotPassword({ email: values.email });
      setSent(true);
    } catch {
      // Always show success to prevent enumeration
      setSent(true);
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[hsl(var(--background-subtle))] px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2">
          <Shield size={18} />
          <span className="font-heading font-semibold">EWMP</span>
        </div>

        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-8 shadow-[var(--shadow-md)]">
          {sent ? (
            <div className="text-center">
              <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-[hsl(var(--success-subtle))]">
                <Mail size={22} className="text-[hsl(var(--success))]" />
              </div>
              <h2 className="font-heading text-xl font-semibold">Check your inbox</h2>
              <p className="mt-2 text-sm text-[hsl(var(--foreground-muted))]">
                If that email is registered, you'll receive a reset link within a few minutes.
              </p>
              <Link
                href="/login"
                className="mt-6 inline-flex items-center gap-1.5 text-sm font-medium text-[hsl(var(--foreground))] hover:underline underline-offset-4"
              >
                <ArrowLeft size={14} /> Back to login
              </Link>
            </div>
          ) : (
            <>
              <h1 className="font-heading text-2xl font-semibold">Reset your password</h1>
              <p className="mt-1.5 text-sm text-[hsl(var(--foreground-muted))]">
                Enter your email and we'll send you a reset link.
              </p>

              <form onSubmit={handleSubmit(onSubmit)} className="mt-6 space-y-4">
                <div className="space-y-1.5">
                  <label className="text-sm font-medium">Email address</label>
                  <input
                    type="email"
                    autoComplete="email"
                    placeholder="you@company.com"
                    {...register("email")}
                    className={cn(
                      "w-full rounded-md border bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none",
                      "placeholder:text-[hsl(var(--foreground-muted))]",
                      "focus:ring-2 focus:ring-[hsl(var(--ring))] focus:ring-offset-1",
                      errors.email
                        ? "border-[hsl(var(--destructive))]"
                        : "border-[hsl(var(--border))] hover:border-[hsl(var(--border-strong))]",
                    )}
                  />
                  {errors.email && (
                    <p className="text-xs text-[hsl(var(--destructive))]">{errors.email.message}</p>
                  )}
                </div>

                <button
                  type="submit"
                  disabled={isLoading}
                  className="flex w-full items-center justify-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2.5 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary-hover))] disabled:opacity-60"
                >
                  {isLoading && <Loader2 size={15} className="animate-spin" />}
                  {isLoading ? "Sending…" : "Send reset link"}
                </button>
              </form>

              <Link
                href="/login"
                className="mt-5 flex items-center gap-1.5 text-sm text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]"
              >
                <ArrowLeft size={13} /> Back to login
              </Link>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
