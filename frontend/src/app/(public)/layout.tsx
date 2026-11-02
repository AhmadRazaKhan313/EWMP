// Public pages for candidates and new hires: reached through a secret link, no login.
export default function PublicLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className="min-h-screen bg-[hsl(var(--background-subtle))] px-4 py-10">
      <div className="mx-auto w-full max-w-2xl">{children}</div>
    </main>
  );
}
