"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Loader2, Shield, ArrowLeft, CheckCircle2, AlertTriangle } from "lucide-react";
import { authService } from "@/services/auth.service";
import { cn } from "@/utils/cn";

const passwordRules = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$/;

const schema = z
  .object({
    new_password: z
      .string()
      .min(8, "Password must be at least 8 characters")
      .regex(
        passwordRules,
        "Include at least one uppercase letter, one lowercase letter, and one number",
      ),
    confirm_password: z.string(),
  })
  .refine((data) => data.new_password === data.confirm_password, {
    message: "Passwords do not match",
    path: ["confirm_password"],
  });

type FormData = z.infer<typeof schema>;

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  const [isLoading, setIsLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormData>({ resolver: zodResolver(schema) });

  async function onSubmit(values: FormData) {
    if (!token) return;
    setServerError(null);
    setIsLoading(true);
    try {
      await authService.resetPassword({
        token,
        new_password: values.new_password,
        confirm_password: values.confirm_password,
      });
      setDone(true);
      setTimeout(() => router.push("/login"), 2500);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { message?: string } } })?.response?.data?.message ??
        "This link is invalid or has expired. Please request a new one.";
      setServerError(msg);
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
          {!token ? (
            <div className="text-center">
              <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-[hsl(var(--destructive)/0.1)]">
                <AlertTriangle size={22} className="text-[hsl(var(--destructive))]" />
              </div>
              <h2 className="font-heading text-xl font-semibold">Invalid link</h2>
              <p className="mt-2 text-sm text-[hsl(var(--foreground-muted))]">
                This link is missing its token. Please use the link from your email,
                or request a new one.
              </p>
              <Link
                href="/forgot-password"
                className="mt-6 inline-flex items-center gap-1.5 text-sm font-medium text-[hsl(var(--foreground))] hover:underline underline-offset-4"
              >
                <ArrowLeft size={14} /> Request a new link
              </Link>
            </div>
          ) : done ? (
            <div className="text-center">
              <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-[hsl(var(--success-subtle))]">
                <CheckCircle2 size={22} className="text-[hsl(var(--success))]" />
              </div>
              <h2 className="font-heading text-xl font-semibold">Password set</h2>
              <p className="mt-2 text-sm text-[hsl(var(--foreground-muted))]">
                Redirecting you to login…
              </p>
            </div>
          ) : (
            <>
              <h1 className="font-heading text-2xl font-semibold">Set your password</h1>
              <p className="mt-1.5 text-sm text-[hsl(var(--foreground-muted))]">
                Choose a password for your EWMP account.
              </p>

              <form onSubmit={handleSubmit(onSubmit)} className="mt-6 space-y-4">
                <div className="space-y-1.5">
                  <label className="text-sm font-medium">New password</label>
                  <input
                    type="password"
                    autoComplete="new-password"
                    placeholder="••••••••"
                    {...register("new_password")}
                    className={cn(
                      "w-full rounded-md border bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none",
                      "placeholder:text-[hsl(var(--foreground-muted))]",
                      "focus:ring-2 focus:ring-[hsl(var(--ring))] focus:ring-offset-1",
                      errors.new_password
                        ? "border-[hsl(var(--destructive))]"
                        : "border-[hsl(var(--border))] hover:border-[hsl(var(--border-strong))]",
                    )}
                  />
                  {errors.new_password && (
                    <p className="text-xs text-[hsl(var(--destructive))]">
                      {errors.new_password.message}
                    </p>
                  )}
                </div>

                <div className="space-y-1.5">
                  <label className="text-sm font-medium">Confirm password</label>
                  <input
                    type="password"
                    autoComplete="new-password"
                    placeholder="••••••••"
                    {...register("confirm_password")}
                    className={cn(
                      "w-full rounded-md border bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none",
                      "placeholder:text-[hsl(var(--foreground-muted))]",
                      "focus:ring-2 focus:ring-[hsl(var(--ring))] focus:ring-offset-1",
                      errors.confirm_password
                        ? "border-[hsl(var(--destructive))]"
                        : "border-[hsl(var(--border))] hover:border-[hsl(var(--border-strong))]",
                    )}
                  />
                  {errors.confirm_password && (
                    <p className="text-xs text-[hsl(var(--destructive))]">
                      {errors.confirm_password.message}
                    </p>
                  )}
                </div>

                {serverError && (
                  <p className="text-xs text-[hsl(var(--destructive))]">{serverError}</p>
                )}

                <button
                  type="submit"
                  disabled={isLoading}
                  className="flex w-full items-center justify-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2.5 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary-hover))] disabled:opacity-60"
                >
                  {isLoading && <Loader2 size={15} className="animate-spin" />}
                  {isLoading ? "Saving…" : "Set password"}
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

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={null}>
      <ResetPasswordForm />
    </Suspense>
  );
}
