/**
 * Profile photo picker, dependents, skills / languages / certifications and
 * how they map to and from the API.
 *
 * Run:  cd frontend && npm test -- photoAndExtras
 */
import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FormProvider, useForm } from "react-hook-form";
import { DependentsSection, ProfilePhotoField, SkillsSection, photoProblem } from "../sections";
import { profileDefaults, profileFromApi, profileToApi, validateProfile, type ProfileFormValues } from "../profileForm";

beforeAll(() => {
  // jsdom has no object URLs.
  URL.createObjectURL = vi.fn(() => "blob:preview");
  URL.revokeObjectURL = vi.fn();
});

let latest: () => ProfileFormValues;
function Harness({ children }: { children: React.ReactNode }) {
  const form = useForm<ProfileFormValues>({ defaultValues: profileDefaults });
  latest = () => form.getValues();
  return <FormProvider {...form}>{children}</FormProvider>;
}

const file = (name: string, type: string, size = 10) => new File([new Uint8Array(size)], name, { type });

describe("photoProblem", () => {
  it("accepts png / jpeg / webp under 5 MB", () => {
    for (const t of ["image/png", "image/jpeg", "image/webp"]) expect(photoProblem(file("a", t))).toBeNull();
  });
  it("rejects other types and big files", () => {
    expect(photoProblem(file("a.gif", "image/gif"))).toMatch(/PNG, JPEG or WebP/);
    expect(photoProblem(file("a.png", "image/png", 5 * 1024 * 1024 + 1))).toMatch(/5 MB/);
  });
});

describe("ProfilePhotoField", () => {
  function setup(over: Partial<React.ComponentProps<typeof ProfilePhotoField>> = {}) {
    const props = {
      name: "Sara Khan", currentUrl: null, file: null, removed: false,
      onPick: vi.fn(), onRemove: vi.fn(), onError: vi.fn(), ...over,
    };
    render(<ProfilePhotoField {...props} />);
    return props;
  }

  it("shows initials until a photo exists, and offers Upload", () => {
    setup();
    expect(screen.getByText("SK")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /upload photo/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /remove/i })).not.toBeInTheDocument();
  });

  it("shows the saved photo from the API's address, with Change and Remove", async () => {
    const props = setup({ currentUrl: "/api/v1/auth/avatar/u1?v=3" });
    expect(screen.getByAltText("Profile photo")).toHaveAttribute("src", "http://localhost:8000/api/v1/auth/avatar/u1?v=3");
    await userEvent.setup().click(screen.getByRole("button", { name: /remove/i }));
    expect(props.onRemove).toHaveBeenCalled();
  });

  it("hands a good file to the form and shows a local preview of it", async () => {
    const user = userEvent.setup();
    const props = setup();
    await user.upload(screen.getByLabelText("Profile photo file"), file("me.png", "image/png"));
    expect(props.onPick).toHaveBeenCalledTimes(1);
    expect(props.onError).not.toHaveBeenCalled();
  });

  it("reports a bad file instead of accepting it", async () => {
    const props = setup();
    // fireEvent-style upload bypasses the input's accept filter, as a drag-drop / renamed file would.
    const input = screen.getByLabelText("Profile photo file") as HTMLInputElement;
    await userEvent.setup({ applyAccept: false }).upload(input, file("evil.exe", "application/octet-stream"));
    expect(props.onError).toHaveBeenCalledWith(expect.stringMatching(/PNG, JPEG or WebP/));
    expect(props.onPick).not.toHaveBeenCalled();
  });

  it("previews the picked file rather than the old photo, and hides a removed one", () => {
    const { unmount } = render(
      <ProfilePhotoField name="A B" currentUrl="/x" file={file("n.png", "image/png")} removed={false}
        onPick={vi.fn()} onRemove={vi.fn()} onError={vi.fn()} />,
    );
    expect(screen.getByAltText("Profile photo")).toHaveAttribute("src", "blob:preview");
    unmount();
    render(<ProfilePhotoField name="A B" currentUrl="/x" file={null} removed
      onPick={vi.fn()} onRemove={vi.fn()} onError={vi.fn()} />);
    expect(screen.queryByAltText("Profile photo")).not.toBeInTheDocument();
    expect(screen.getByText("AB")).toBeInTheDocument();
  });
});

describe("Dependents, skills, languages, certifications", () => {
  it("adds and removes rows", async () => {
    const user = userEvent.setup();
    render(<Harness><DependentsSection /><SkillsSection /></Harness>);
    await user.click(screen.getByRole("button", { name: /add dependent/i }));
    await user.type(screen.getByLabelText("Dependent 1 name"), "Ayesha");
    await user.selectOptions(screen.getByLabelText("Dependent 1 relationship"), "child");
    await user.click(screen.getByRole("button", { name: /add skill/i }));
    await user.type(screen.getByLabelText("Skill 1 name"), "Python");
    await user.selectOptions(screen.getByLabelText("Skill 1 level"), "expert");
    await user.click(screen.getByRole("button", { name: /add language/i }));
    await user.type(screen.getByLabelText("Language 1 name"), "Urdu");
    await user.click(screen.getByRole("button", { name: /add certification/i }));
    await user.type(screen.getByLabelText("Certification 1 name"), "PMP");

    const v = latest();
    expect(v.dependents[0]).toMatchObject({ name: "Ayesha", relationship: "child" });
    expect(v.skills[0]).toMatchObject({ name: "Python", level: "expert" });
    expect(v.languages[0]!.name).toBe("Urdu");
    expect(v.certifications[0]!.name).toBe("PMP");

    await user.click(screen.getByRole("button", { name: "Remove skill 1" }));
    expect(latest().skills).toHaveLength(0);
  });
});

describe("API mapping for the new lists", () => {
  it("round-trips through the API shape and drops blank rows", () => {
    const form = profileFromApi({
      dependents: [{ name: "Ayesha", relationship: "child", date_of_birth: "2015-05-05" }],
      skills: [{ name: "Python", level: "expert" }],
      languages: [{ name: "Urdu", fluency: "native" }],
      certifications: [{ name: "PMP", issued_by: "PMI", issued_date: "2023-01-01", expiry_date: null }],
      driving_license_number: "LHR-1", driving_license_expiry: "2030-01-01",
    });
    expect(form.driving_license_number).toBe("LHR-1");
    form.skills.push({ name: "  ", level: "" });
    const out = profileToApi(form);
    expect(out.dependents).toEqual([{ name: "Ayesha", relationship: "child", date_of_birth: "2015-05-05" }]);
    expect(out.skills).toEqual([{ name: "Python", level: "expert" }]);
    expect(out.languages).toEqual([{ name: "Urdu", fluency: "native" }]);
    expect(out.certifications[0]).toEqual({ name: "PMP", issued_by: "PMI", issued_date: "2023-01-01", expiry_date: null });
    expect(out.driving_license_expiry).toBe("2030-01-01");
  });

  it("asks for a name on a dependent row that has other details", () => {
    const v = { ...profileDefaults, dependents: [{ name: "", relationship: "child" }] };
    expect(validateProfile(v)?.tab).toBe("personal");
  });
});
