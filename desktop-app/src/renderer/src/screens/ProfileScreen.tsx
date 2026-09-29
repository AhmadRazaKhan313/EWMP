import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, Loader2, User as UserIcon, Mail, Phone, ShieldCheck, Pencil } from "lucide-react";
import { getMe, resolveAvatarUrl, updateProfile, uploadAvatar } from "../services/authService";
import { useAuthStore } from "../store/authStore";
import { Badge, Button, Card, CardHeader, ErrorState, Field, Skeleton, cn, inputClass } from "../components/ui";

const MAX_AVATAR_BYTES = 5 * 1024 * 1024;
const ACCEPTED_AVATAR_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);

/**
 * Profile — view and edit the four fields PATCH /auth/me accepts, plus
 * avatar upload. Email, roles and org membership are read-only here
 * because they go through an admin flow, so they are shown as facts
 * rather than as disabled inputs that look broken.
 *
 * Restyled onto the shared primitives; the avatar size/type limits are
 * still enforced client-side first so a bad file never makes a doomed
 * round trip (backend caps at 5 MB, PNG/JPEG/WebP only).
 */
export default function ProfileScreen(): JSX.Element {
  const queryClient = useQueryClient();
  const authUser = useAuthStore((s) => s.user);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [avatarError, setAvatarError] = useState<string | null>(null);

  const profileQuery = useQuery({ queryKey: ["profile", "me"], queryFn: getMe });
  const avatarSrcQuery = useQuery({
    queryKey: ["profile", "avatar-src", profileQuery.data?.avatar_url],
    queryFn: () => resolveAvatarUrl(profileQuery.data?.avatar_url ?? null),
    enabled: !!profileQuery.data,
  });

  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [phone, setPhone] = useState("");
  const [bio, setBio] = useState("");
  const [editing, setEditing] = useState(false);

  const profile = profileQuery.data;

  function startEditing(): void {
    if (!profile) return;
    setFirstName(profile.first_name);
    setLastName(profile.last_name);
    setPhone(profile.phone ?? "");
    setBio(profile.bio ?? "");
    setEditing(true);
  }

  const saveMutation = useMutation({
    mutationFn: () => updateProfile({ first_name: firstName, last_name: lastName, phone, bio }),
    onSuccess: (updated) => {
      queryClient.setQueryData(["profile", "me"], updated);
      // Keep the sidebar in sync too — it reads full_name from authStore,
      // not from this screen's query.
      if (authUser) {
        useAuthStore.setState({
          user: { ...authUser, full_name: updated.full_name, avatar_url: updated.avatar_url },
        });
      }
      setEditing(false);
    },
  });

  const avatarMutation = useMutation({
    mutationFn: uploadAvatar,
    onSuccess: ({ avatar_url }) => {
      setAvatarError(null);
      queryClient.setQueryData(["profile", "me"], (old: typeof profile) => (old ? { ...old, avatar_url } : old));
      void queryClient.invalidateQueries({ queryKey: ["profile", "avatar-src"] });
      if (authUser) {
        useAuthStore.setState({ user: { ...authUser, avatar_url } });
      }
    },
    onError: () => setAvatarError("That image didn't upload. Try a PNG, JPEG or WebP under 5 MB."),
  });

  function handleAvatarPick(e: React.ChangeEvent<HTMLInputElement>): void {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-picking the same file later
    if (!file) return;

    if (!ACCEPTED_AVATAR_TYPES.has(file.type)) {
      setAvatarError("Choose a PNG, JPEG, or WebP image.");
      return;
    }
    if (file.size > MAX_AVATAR_BYTES) {
      setAvatarError("That image is over 5 MB. Choose a smaller one.");
      return;
    }
    setAvatarError(null);
    avatarMutation.mutate(file);
  }

  if (profileQuery.isLoading || !profile) {
    return (
      <div className="flex w-full flex-col gap-[18px] p-6">
        <Skeleton className="h-[120px] w-full rounded-[var(--radius-card)]" />
        <Skeleton className="h-[220px] w-full rounded-[var(--radius-card)]" />
      </div>
    );
  }

  const initials =
    [profile.first_name?.[0], profile.last_name?.[0]].filter(Boolean).join("").toUpperCase() || "?";

  return (
    <div className="flex w-full flex-col gap-[18px] p-6">
      <header>
        <h1 className="font-heading text-[22px] font-semibold tracking-tight text-[hsl(var(--foreground))]">
          Profile
        </h1>
        <p className="mt-0.5 text-xs text-[hsl(var(--foreground-muted))]">
          Your details, photo and account access
        </p>
      </header>

      {/* Identity card — indigo, matching the emphasis the dashboard band
          gets, since this is the one "this is you" surface in the app. */}
      <Card className="flex flex-wrap items-center gap-5 bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]">
        <button
          data-testid="avatar-upload-button"
          onClick={() => fileInputRef.current?.click()}
          disabled={avatarMutation.isPending}
          aria-label="Change profile photo"
          className="group relative flex h-20 w-20 shrink-0 items-center justify-center overflow-hidden rounded-full bg-white/15 font-heading text-xl font-semibold text-white disabled:opacity-70"
        >
          {avatarSrcQuery.data ? (
            <img src={avatarSrcQuery.data} alt="Profile avatar" className="h-full w-full object-cover" />
          ) : (
            initials
          )}
          <span className="absolute inset-0 flex items-center justify-center bg-black/45 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
            {avatarMutation.isPending ? (
              <Loader2 size={18} className="animate-spin text-white" />
            ) : (
              <Camera size={18} className="text-white" />
            )}
          </span>
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          className="hidden"
          data-testid="avatar-file-input"
          onChange={handleAvatarPick}
        />

        <div className="min-w-0 flex-1">
          <p className="font-heading text-xl font-semibold tracking-tight">{profile.full_name}</p>
          <p className="mt-0.5 flex items-center gap-1.5 text-sm text-white/75">
            <Mail size={13} />
            {profile.email}
          </p>
          {profile.roles.length > 0 && (
            <div className="mt-2.5 flex flex-wrap gap-1.5">
              {profile.roles.map((r) => (
                <span
                  key={r}
                  className="rounded-[var(--radius-chip)] bg-white/15 px-2 py-0.5 text-[11px] font-medium text-white"
                >
                  {r}
                </span>
              ))}
            </div>
          )}
        </div>

        {!editing && (
          <button
            data-testid="edit-profile-button"
            onClick={startEditing}
            className="inline-flex items-center gap-2 rounded-[var(--radius-control)] bg-white/15 px-3.5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-white/25"
          >
            <Pencil size={14} />
            Edit profile
          </button>
        )}
      </Card>

      {avatarError && <ErrorState message={avatarError} />}

      {!editing ? (
        <Card>
          <CardHeader title="Your details" />
          <dl className="grid grid-cols-1 gap-x-8 gap-y-3.5 sm:grid-cols-2">
            <DetailRow label="First name" value={profile.first_name} />
            <DetailRow label="Last name" value={profile.last_name} />
            <DetailRow label="Phone" value={profile.phone || "Not set"} icon={<Phone size={13} />} />
            <DetailRow
              label="Two-factor authentication"
              value={profile.is_2fa_enabled ? "Enabled" : "Not enabled"}
              icon={<ShieldCheck size={13} />}
              badge={
                <Badge variant={profile.is_2fa_enabled ? "success" : "outline"}>
                  {profile.is_2fa_enabled ? "On" : "Off"}
                </Badge>
              }
            />
            <div className="sm:col-span-2">
              <dt className="text-xs font-medium text-[hsl(var(--foreground-muted))]">Bio</dt>
              <dd className="mt-1 text-sm leading-relaxed text-[hsl(var(--foreground))]">
                {profile.bio || <span className="text-[hsl(var(--foreground-muted))]">Nothing added yet.</span>}
              </dd>
            </div>
          </dl>
        </Card>
      ) : (
        <Card>
          <CardHeader title="Edit your details" />
          <form
            data-testid="profile-edit-form"
            onSubmit={(e) => {
              e.preventDefault();
              saveMutation.mutate();
            }}
            className="flex flex-col gap-3.5"
          >
            <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
              <Field label="First name">
                <input
                  data-testid="input-first-name"
                  value={firstName}
                  onChange={(e) => setFirstName(e.target.value)}
                  required
                  className={inputClass}
                />
              </Field>
              <Field label="Last name">
                <input
                  data-testid="input-last-name"
                  value={lastName}
                  onChange={(e) => setLastName(e.target.value)}
                  required
                  className={inputClass}
                />
              </Field>
            </div>
            <Field label="Phone">
              <input
                data-testid="input-phone"
                type="tel"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                className={inputClass}
              />
            </Field>
            <Field label="Bio">
              <textarea
                data-testid="input-bio"
                value={bio}
                onChange={(e) => setBio(e.target.value)}
                rows={3}
                className={cn(inputClass, "resize-none")}
              />
            </Field>

            <div className="flex gap-2.5">
              <Button type="button" variant="secondary" size="lg" className="flex-1" onClick={() => setEditing(false)}>
                Cancel
              </Button>
              <Button
                type="submit"
                data-testid="save-profile-button"
                disabled={saveMutation.isPending || !firstName || !lastName}
                size="lg"
                className="flex-1"
              >
                {saveMutation.isPending && <Loader2 size={15} className="animate-spin" />}
                Save changes
              </Button>
            </div>

            {saveMutation.isError && (
              <p role="alert" className="text-xs text-[hsl(var(--destructive))]">
                Those changes didn&apos;t save. Check your connection to the server and try again.
              </p>
            )}
          </form>
        </Card>
      )}

      {/* Mirrors the disclosure in ConsentNotice. Repeating it here, where
          someone goes looking for it later, is the point — a consent
          screen seen once at enrollment is not a durable answer to "what
          does this app record about me". */}
      <Card>
        <CardHeader title="What this app records" icon={<UserIcon size={16} />} />
        <p className="text-sm leading-relaxed text-[hsl(var(--foreground))]">
          Your check-in and check-out times, your breaks, and the leave and payslip records your organisation keeps
          for you.
        </p>
        <p className="mt-2.5 border-t border-[hsl(var(--border))] pt-2.5 text-xs leading-relaxed text-[hsl(var(--foreground-muted))]">
          Your organisation may also have device monitoring enabled. If it does, you agreed to it on the consent
          screen when this device was enrolled, and your HR admin can tell you exactly what is collected.
        </p>
      </Card>
    </div>
  );
}

function DetailRow({
  label,
  value,
  icon,
  badge,
}: {
  label: string;
  value: string;
  icon?: JSX.Element;
  badge?: JSX.Element;
}): JSX.Element {
  return (
    <div>
      <dt className="flex items-center gap-1.5 text-xs font-medium text-[hsl(var(--foreground-muted))]">
        {icon}
        {label}
      </dt>
      <dd className="mt-0.5 flex items-center gap-2 text-sm font-medium text-[hsl(var(--foreground))]">
        {value}
        {badge}
      </dd>
    </div>
  );
}
