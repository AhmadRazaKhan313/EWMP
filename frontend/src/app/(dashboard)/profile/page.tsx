"use client";

import { useRef, useState } from "react";
import { Camera, Loader2 } from "lucide-react";
import { Button, Card, PageHeader } from "@/components/atoms";
import { useAuthStore } from "@/store/auth.store";
import { authService } from "@/services/auth.service";

const inputClass =
  "w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm text-[hsl(var(--foreground))] outline-none focus:border-[hsl(var(--border-strong))]";

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}): JSX.Element {
  return (
    <div>
      <label className="mb-1.5 block text-xs font-medium text-[hsl(var(--foreground-muted))]">
        {label}
      </label>
      {children}
    </div>
  );
}

export default function ProfilePage(): JSX.Element {
  const { user, setUser } = useAuthStore();

  const [firstName, setFirstName] = useState(user?.first_name ?? "");
  const [lastName, setLastName] = useState(user?.last_name ?? "");
  const [phone, setPhone] = useState(user?.phone ?? "");
  const [bio, setBio] = useState(user?.bio ?? "");
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileMessage, setProfileMessage] = useState<string | null>(null);

  const [uploadingAvatar, setUploadingAvatar] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);
  const [passwordMessage, setPasswordMessage] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);

  async function handleSaveProfile(): Promise<void> {
    setSavingProfile(true);
    setProfileMessage(null);
    try {
      const updated = await authService.updateProfile({
        first_name: firstName,
        last_name: lastName,
        phone,
        bio,
      });
      setUser(updated);
      setProfileMessage("Profile updated.");
    } catch {
      setProfileMessage("Couldn't save profile — please try again.");
    } finally {
      setSavingProfile(false);
    }
  }

  async function handleAvatarSelected(e: React.ChangeEvent<HTMLInputElement>): Promise<void> {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadingAvatar(true);
    try {
      const { avatar_url } = await authService.uploadAvatar(file);
      if (user) setUser({ ...user, avatar_url });
    } finally {
      setUploadingAvatar(false);
      e.target.value = "";
    }
  }

  async function handleChangePassword(): Promise<void> {
    setPasswordError(null);
    setPasswordMessage(null);
    if (newPassword !== confirmPassword) {
      setPasswordError("New password and confirmation don't match.");
      return;
    }
    setSavingPassword(true);
    try {
      await authService.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
        confirm_password: confirmPassword,
      });
      setPasswordMessage("Password changed.");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch {
      setPasswordError("Couldn't change password — check your current password and try again.");
    } finally {
      setSavingPassword(false);
    }
  }

  if (!user) {
    return (
      <div className="flex h-40 items-center justify-center text-sm text-[hsl(var(--foreground-muted))]">
        Loading…
      </div>
    );
  }

  return (
    <div className="max-w-2xl space-y-6">
      <PageHeader title="Profile" description="Manage your personal account details." />

      <Card>
        <div className="flex items-center gap-4">
          <div className="relative">
            <div className="flex h-16 w-16 items-center justify-center overflow-hidden rounded-full bg-[hsl(var(--primary))] text-lg font-bold text-[hsl(var(--primary-foreground))]">
              {user.avatar_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={user.avatar_url} alt={user.full_name} className="h-full w-full object-cover" />
              ) : (
                <span>
                  {user.first_name?.[0]}
                  {user.last_name?.[0]}
                </span>
              )}
            </div>
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadingAvatar}
              className="absolute -bottom-1 -right-1 flex h-6 w-6 items-center justify-center rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--background))] shadow-sm hover:bg-[hsl(var(--accent))]"
            >
              {uploadingAvatar ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <Camera size={12} />
              )}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              onChange={(e) => void handleAvatarSelected(e)}
            />
          </div>
          <div>
            <p className="font-heading text-sm font-semibold">{user.full_name}</p>
            <p className="text-xs text-[hsl(var(--foreground-muted))]">{user.email}</p>
          </div>
        </div>

        <div className="mt-6 grid grid-cols-2 gap-4">
          <Field label="First name">
            <input className={inputClass} value={firstName} onChange={(e) => setFirstName(e.target.value)} />
          </Field>
          <Field label="Last name">
            <input className={inputClass} value={lastName} onChange={(e) => setLastName(e.target.value)} />
          </Field>
          <Field label="Email">
            <input className={inputClass} value={user.email} disabled title="Contact an admin to change your email" />
          </Field>
          <Field label="Phone">
            <input className={inputClass} value={phone} onChange={(e) => setPhone(e.target.value)} />
          </Field>
          <div className="col-span-2">
            <Field label="Bio">
              <textarea
                className={`${inputClass} min-h-[80px] resize-none`}
                value={bio}
                onChange={(e) => setBio(e.target.value)}
              />
            </Field>
          </div>
        </div>

        <div className="mt-4 flex items-center gap-3">
          <Button onClick={() => void handleSaveProfile()} disabled={savingProfile}>
            {savingProfile ? "Saving…" : "Save changes"}
          </Button>
          {profileMessage && (
            <span className="text-xs text-[hsl(var(--foreground-muted))]">{profileMessage}</span>
          )}
        </div>
      </Card>

      <Card>
        <p className="mb-4 font-heading text-sm font-semibold">Change password</p>
        <div className="space-y-4">
          <Field label="Current password">
            <input
              type="password"
              className={inputClass}
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
            />
          </Field>
          <Field label="New password">
            <input
              type="password"
              className={inputClass}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
            />
          </Field>
          <Field label="Confirm new password">
            <input
              type="password"
              className={inputClass}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
            />
          </Field>
        </div>
        <div className="mt-4 flex items-center gap-3">
          <Button onClick={() => void handleChangePassword()} disabled={savingPassword}>
            {savingPassword ? "Changing…" : "Change password"}
          </Button>
          {passwordMessage && (
            <span className="text-xs text-[hsl(var(--success))]">{passwordMessage}</span>
          )}
          {passwordError && (
            <span className="text-xs text-[hsl(var(--destructive))]">{passwordError}</span>
          )}
        </div>
      </Card>
    </div>
  );
}
