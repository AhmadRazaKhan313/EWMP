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
    <div className="flex min-h-screen">
      {/* Left panel — branding */}
      <div className="hidden w-1/2 flex-col justify-between bg-[hsl(var(--foreground))] p-12 lg:flex">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/10">
            <Shield size={16} className="text-white" />
          </div>
          <span className="font-heading text-lg font-semibold text-white">EWMP</span>
        </div>

        <div>
          <blockquote className="space-y-4">
            <p className="text-xl font-medium leading-relaxed text-white/90">
              "The platform that brought our HR, IT, and operations teams onto a
              single pane of glass. Payroll used to take three days — now it's
              done in an afternoon."
            </p>
            <footer className="text-sm text-white/50">
              — Chief People Officer, Meridian Technologies
            </footer>
          </blockquote>
        </div>

        <div className="flex gap-6 text-xs text-white/40">
          <span>SOC 2 Type II</span>
          <span>ISO 27001</span>
          <span>GDPR Compliant</span>
        </div>
      </div>

      {/* Right panel — form */}
      <div className="flex flex-1 flex-col items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">
          {/* Mobile logo */}
          <div className="mb-8 flex items-center gap-2 lg:hidden">
            <Shield size={20} />
            <span className="font-heading text-lg font-semibold">EWMP</span>
          </div>

          <div className="mb-8">
            <h1 className="font-heading text-2xl font-semibold tracking-tight">
              Sign in to your account
            </h1>
            <p className="mt-1.5 text-sm text-[hsl(var(--foreground-muted))]">
              Enter your email and password to continue
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
                  "w-full rounded-md border bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none transition-colors",
                  "placeholder:text-[hsl(var(--foreground-muted))]",
                  "focus:ring-2 focus:ring-[hsl(var(--ring))] focus:ring-offset-1",
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
                  className="text-xs text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]"
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
                    "w-full rounded-md border bg-[hsl(var(--background))] px-3 py-2 pr-10 text-sm outline-none transition-colors",
                    "placeholder:text-[hsl(var(--foreground-muted))]",
                    "focus:ring-2 focus:ring-[hsl(var(--ring))] focus:ring-offset-1",
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
                "flex w-full items-center justify-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2.5 text-sm font-medium text-[hsl(var(--primary-foreground))] transition-colors",
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
              className="font-medium text-[hsl(var(--foreground))] underline-offset-4 hover:underline"
            >
              Start free trial
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
