import { OnboardingNav } from "@/components/onboarding/OnboardingNav";

export default function OnboardingLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="space-y-6">
      <OnboardingNav />
      {children}
    </div>
  );
}
