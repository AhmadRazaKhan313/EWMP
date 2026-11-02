"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Eye, EyeOff, Loader2, Shield } from "lucide-react";
import { toast } from "sonner";
import { authService } from "@/services/auth.service";
import { useAuthStore } from "@/store/auth.store";
import { cn } from "@/utils/cn";

const loginSchema = z.object({
  email: z.string().email("Enter a valid email address"),
  password: z.string().min(1, "Password is required"),
});

type LoginForm = z.infer<typeof loginSchema>;

// Branding copy — edit these three lines to change the left panel.
const BRAND_NAME = "Ahmad HRMS";
const BRAND_TITLE = "Everything your workforce needs, in one place.";
const BRAND_SUBTITLE =
  "Attendance, payroll, leave and people management for your whole team.";

export default function LoginPage() {
  const router = useRouter();
  const setUser = useAuthStore((s) => s.setUser);
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginForm>({ resolver: zodResolver(loginSchema) });

  async function onSubmit(values: LoginForm) {
    setIsLoading(true);
    try {
      const response = await authService.login(values);
      // Load full user profile into store
      const me = await authService.getMe();
      setUser(me);
      toast.success(`Welcome back, ${response.user.first_name}!`);
      router.replace("/dashboard");
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { message?: string } } })?.response?.data
          ?.message ?? "Invalid email or password";
      toast.error(message);
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen bg-[hsl(var(--background))]">
      {/* Left panel — brand */}
      <div className="relative hidden w-1/2 flex-col justify-between overflow-hidden border-r border-[hsl(var(--border))] bg-[hsl(var(--brand-25))] p-12 lg:flex">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_50%_at_85%_10%,hsl(var(--brand-100)),transparent)]" />

        <div className="relative flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--primary))] shadow-[var(--shadow-sm)]">
            <Shield size={18} className="text-[hsl(var(--primary-foreground))]" />
          </div>
          <span className="font-heading text-lg font-semibold text-[hsl(var(--foreground))]">
            {BRAND_NAME}
          </span>
        </div>

        <div className="relative max-w-md">
          <h2 className="font-heading text-4xl font-semibold leading-tight tracking-tight text-[hsl(var(--foreground))]">
            {BRAND_TITLE}
          </h2>
          <p className="mt-4 text-base leading-relaxed text-[hsl(var(--foreground-muted))]">
            {BRAND_SUBTITLE}
          </p>
        </div>

        {/* Concentric rings, echoing the dashboard activity gauge */}
        <svg
          aria-hidden="true"
          viewBox="0 0 320 320"
          className="pointer-events-none absolute -right-32 -top-32 h-[460px] w-[460px]"
        >
          <circle cx="160" cy="160" r="150" fill="none" stroke="hsl(var(--brand-100))" strokeWidth="18" />
          <circle cx="160" cy="160" r="150" fill="none" stroke="hsl(var(--brand-700))" strokeWidth="18" strokeLinecap="round" strokeDasharray="620 943" transform="rotate(-90 160 160)" />
          <circle cx="160" cy="160" r="112" fill="none" stroke="hsl(var(--brand-100))" strokeWidth="18" />
          <circle cx="160" cy="160" r="112" fill="none" stroke="hsl(var(--brand-400))" strokeWidth="18" strokeLinecap="round" strokeDasharray="450 704" transform="rotate(-90 160 160)" />
          <circle cx="160" cy="160" r="74" fill="none" stroke="hsl(var(--brand-100))" strokeWidth="18" />
          <circle cx="160" cy="160" r="74" fill="none" stroke="hsl(var(--brand-600))" strokeWidth="18" strokeLinecap="round" strokeDasharray="280 465" transform="rotate(-90 160 160)" />
        </svg>
      </div>

      {/* Right panel — form */}
      <div className="flex flex-1 flex-col items-center justify-center bg-[hsl(var(--background-subtle))] px-6 py-12 lg:bg-[hsl(var(--background))]">
        <div className="w-full max-w-sm rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-8 shadow-[var(--shadow-md)] lg:max-w-md lg:border-0 lg:p-0 lg:shadow-none">
          {/* Mobile logo */}
          <div className="mb-8 flex items-center gap-2 lg:hidden">
            <Shield size={20} className="text-[hsl(var(--primary))]" />
            <span className="font-heading text-lg font-semibold">{BRAND_NAME}</span>
          </div>

          <div className="mb-8">
            <h1 className="font-heading text-3xl font-semibold tracking-tight">
              Welcome back
            </h1>
            <p className="mt-1.5 text-sm text-[hsl(var(--foreground-muted))]">
              Sign in to continue to your account
            </p>
          </div>

          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            {/* Email */}
            <div className="space-y-1.5">
              <label
                htmlFor="email"
                className="text-sm font-medium text-[hsl(var(--foreground))]"
              >
                Email address
              </label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                placeholder="you@company.com"
                {...register("email")}
                className={cn(
                  "w-full rounded-lg border bg-[hsl(var(--background))] px-3.5 py-2.5 text-sm shadow-[var(--shadow-xs)] outline-none transition-colors",
                  "placeholder:text-[hsl(var(--foreground-muted))]",
                  "focus:border-[hsl(var(--brand-300))] focus:ring-4 focus:ring-[hsl(var(--brand-100))]",
                  errors.email
                    ? "border-[hsl(var(--destructive))]"
                    : "border-[hsl(var(--border))] hover:border-[hsl(var(--border-strong))]",
                )}
              />
              {errors.email && (
                <p className="text-xs text-[hsl(var(--destructive))]">
                  {errors.email.message}
                </p>
              )}
            </div>

            {/* Password */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label
                  htmlFor="password"
                  className="text-sm font-medium text-[hsl(var(--foreground))]"
                >
                  Password
                </label>
                <Link
                  href="/forgot-password"
                  className="text-xs font-medium text-[hsl(var(--primary))] hover:text-[hsl(var(--primary-hover))]"
                >
                  Forgot password?
                </Link>
              </div>
              <div className="relative">
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  placeholder="••••••••"
                  {...register("password")}
                  className={cn(
                    "w-full rounded-lg border bg-[hsl(var(--background))] px-3.5 py-2.5 pr-10 text-sm shadow-[var(--shadow-xs)] outline-none transition-colors",
                    "placeholder:text-[hsl(var(--foreground-muted))]",
                    "focus:border-[hsl(var(--brand-300))] focus:ring-4 focus:ring-[hsl(var(--brand-100))]",
                    errors.password
                      ? "border-[hsl(var(--destructive))]"
                      : "border-[hsl(var(--border))] hover:border-[hsl(var(--border-strong))]",
                  )}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]"
                >
                  {showPassword ? <EyeOff size={15} /> : <Eye size={15} />}
                </button>
              </div>
              {errors.password && (
                <p className="text-xs text-[hsl(var(--destructive))]">
                  {errors.password.message}
                </p>
              )}
            </div>

            {/* Submit */}
            <button
              type="submit"
              disabled={isLoading}
              className={cn(
                "flex w-full items-center justify-center gap-2 rounded-lg bg-[hsl(var(--primary))] px-4 py-2.5 text-sm font-semibold shadow-[var(--shadow-xs)] text-[hsl(var(--primary-foreground))] transition-colors",
                "hover:bg-[hsl(var(--primary-hover))]",
                "disabled:cursor-not-allowed disabled:opacity-60",
              )}
            >
              {isLoading && <Loader2 size={15} className="animate-spin" />}
              {isLoading ? "Signing in..." : "Sign in"}
            </button>
          </form>

          <p className="mt-6 text-center text-sm text-[hsl(var(--foreground-muted))]">
            Don&apos;t have an account?{" "}
            <Link
              href="/register"
              className="font-semibold text-[hsl(var(--primary))] underline-offset-4 hover:underline"
            >
              Start free trial
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
