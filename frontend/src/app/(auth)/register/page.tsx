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

const registerSchema = z
  .object({
    org_name: z.string().min(2, "Organization name must be at least 2 characters"),
    org_slug: z
      .string()
      .min(2, "Slug must be at least 2 characters")
      .max(50, "Slug too long")
      .regex(/^[a-z0-9][a-z0-9-]*[a-z0-9]$/, "Lowercase letters, numbers, and hyphens only"),
    first_name: z.string().min(1, "First name is required"),
    last_name: z.string().min(1, "Last name is required"),
    email: z.string().email("Enter a valid email"),
    password: z
      .string()
      .min(8, "Minimum 8 characters")
      .regex(/[A-Z]/, "Must contain an uppercase letter")
      .regex(/[a-z]/, "Must contain a lowercase letter")
      .regex(/\d/, "Must contain a number"),
    confirm_password: z.string(),
  })
  .refine((d) => d.password === d.confirm_password, {
    message: "Passwords do not match",
    path: ["confirm_password"],
  });

type RegisterForm = z.infer<typeof registerSchema>;

function Field({
  label,
  error,
  children,
  hint,
}: {
  label: string;
  error?: string;
  children: React.ReactNode;
  hint?: string;
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-sm font-medium text-[hsl(var(--foreground))]">{label}</label>
      {children}
      {hint && !error && <p className="text-xs text-[hsl(var(--foreground-muted))]">{hint}</p>}
      {error && <p className="text-xs text-[hsl(var(--destructive))]">{error}</p>}
    </div>
  );
}

function Input({
  error,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement> & { error?: boolean }) {
  return (
    <input
      {...props}
      className={cn(
        "w-full rounded-md border bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none transition-colors",
        "placeholder:text-[hsl(var(--foreground-muted))]",
        "focus:ring-2 focus:ring-[hsl(var(--ring))] focus:ring-offset-1",
        error
          ? "border-[hsl(var(--destructive))]"
          : "border-[hsl(var(--border))] hover:border-[hsl(var(--border-strong))]",
      )}
    />
  );
}

export default function RegisterPage() {
  const router = useRouter();
  const setUser = useAuthStore((s) => s.setUser);
  const [showPwd, setShowPwd] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    formState: { errors },
  } = useForm<RegisterForm>({ resolver: zodResolver(registerSchema) });

  // Auto-generate slug from org name
  function handleOrgNameChange(e: React.ChangeEvent<HTMLInputElement>) {
    const val = e.target.value;
    register("org_name").onChange(e);
    const slug = val
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "");
    if (slug.length >= 2)setValue("org_slug", slug);
  }

  async function onSubmit(values: RegisterForm) {
    setIsLoading(true);
    try {
      await authService.register({
        org_name: values.org_name,
        org_slug: values.org_slug,
        first_name: values.first_name,
        last_name: values.last_name,
        email: values.email,
        password: values.password,
      });
      const me = await authService.getMe();
      setUser(me);
      toast.success("Organization created! Welcome to EWMP.");
      router.replace("/dashboard");
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { message?: string } } })?.response?.data
          ?.message ?? "Registration failed. Please try again.";
      toast.error(msg);
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[hsl(var(--background-subtle))] px-4 py-12">
      <div className="w-full max-w-lg">
        {/* Logo */}
        <div className="mb-8 flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[hsl(var(--foreground))]">
            <Shield size={16} className="text-white" />
          </div>
          <span className="font-heading text-lg font-semibold">EWMP</span>
        </div>

        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-8 shadow-[var(--shadow-md)]">
          <div className="mb-7">
            <h1 className="font-heading text-2xl font-semibold tracking-tight">
              Start your free trial
            </h1>
            <p className="mt-1.5 text-sm text-[hsl(var(--foreground-muted))]">
              14 days free, no credit card required.
            </p>
          </div>

          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            {/* Org name + slug */}
            <div className="grid grid-cols-2 gap-4">
              <Field label="Organization Name" error={errors.org_name?.message}>
                <Input
                  placeholder="Acme Corp"
                  error={!!errors.org_name}
                  {...register("org_name", { onChange: handleOrgNameChange })}
                />
              </Field>
              <Field
                label="Organization Slug"
                error={errors.org_slug?.message}
                hint="Used as your URL identifier"
              >
                <Input
                  placeholder="acme-corp"
                  error={!!errors.org_slug}
                  {...register("org_slug")}
                />
              </Field>
            </div>

            {/* Name */}
            <div className="grid grid-cols-2 gap-4">
              <Field label="First Name" error={errors.first_name?.message}>
                <Input
                  placeholder="John"
                  autoComplete="given-name"
                  error={!!errors.first_name}
                  {...register("first_name")}
                />
              </Field>
              <Field label="Last Name" error={errors.last_name?.message}>
                <Input
                  placeholder="Smith"
                  autoComplete="family-name"
                  error={!!errors.last_name}
                  {...register("last_name")}
                />
              </Field>
            </div>

            {/* Email */}
            <Field label="Work Email" error={errors.email?.message}>
              <Input
                type="email"
                placeholder="john@acmecorp.com"
                autoComplete="email"
                error={!!errors.email}
                {...register("email")}
              />
            </Field>

            {/* Password */}
            <Field label="Password" error={errors.password?.message}>
              <div className="relative">
                <Input
                  type={showPwd ? "text" : "password"}
                  placeholder="Min. 8 chars, uppercase & number"
                  autoComplete="new-password"
                  error={!!errors.password}
                  {...register("password")}
                />
                <button
                  type="button"
                  onClick={() => setShowPwd((v) => !v)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]"
                >
                  {showPwd ? <EyeOff size={15} /> : <Eye size={15} />}
                </button>
              </div>
            </Field>

            {/* Confirm */}
            <Field label="Confirm Password" error={errors.confirm_password?.message}>
              <Input
                type="password"
                placeholder="Re-enter password"
                autoComplete="new-password"
                error={!!errors.confirm_password}
                {...register("confirm_password")}
              />
            </Field>

            <button
              type="submit"
              disabled={isLoading}
              className={cn(
                "mt-2 flex w-full items-center justify-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2.5 text-sm font-medium text-[hsl(var(--primary-foreground))] transition-colors",
                "hover:bg-[hsl(var(--primary-hover))] disabled:cursor-not-allowed disabled:opacity-60",
              )}
            >
              {isLoading && <Loader2 size={15} className="animate-spin" />}
              {isLoading ? "Creating account…" : "Create account"}
            </button>
          </form>

          <p className="mt-5 text-center text-sm text-[hsl(var(--foreground-muted))]">
            Already have an account?{" "}
            <Link
              href="/login"
              className="font-medium text-[hsl(var(--foreground))] underline-offset-4 hover:underline"
            >
              Sign in
            </Link>
          </p>
        </div>

        <p className="mt-5 text-center text-xs text-[hsl(var(--foreground-muted))]">
          By creating an account you agree to our{" "}
          <Link href="#" className="underline underline-offset-2">Terms</Link> and{" "}
          <Link href="#" className="underline underline-offset-2">Privacy Policy</Link>.
        </p>
      </div>
    </div>
  );
}
