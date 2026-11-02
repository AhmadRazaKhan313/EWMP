/**
 * E-03: tax / EOBI / PF / visa numbers and the extra personal details on the
 * Add/Edit Employee form: they are typed, mapped to the API and read back.
 *
 * Run:  cd frontend && npm test -- morePersonalFields
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FormProvider, useForm } from "react-hook-form";
import { PersonalExtrasSection } from "../sections";
import { profileDefaults, profileFromApi, profileToApi, type ProfileFormValues } from "../profileForm";

let latest: () => ProfileFormValues;
function Harness() {
  const form = useForm<ProfileFormValues>({ defaultValues: { ...profileDefaults } });
  latest = () => form.getValues();
  return <FormProvider {...form}><PersonalExtrasSection /></FormProvider>;
}

describe("mapping", () => {
  it("sends blanks as null and only the filled social links", () => {
    const api = profileToApi({
      ...profileDefaults, tax_number: " NTN-1 ", visa_expiry: "",
      social_links: { ...profileDefaults.social_links, linkedin: "https://l.in/x" },
    });
    expect(api.tax_number).toBe("NTN-1");
    expect(api.visa_expiry).toBeNull();
    expect(api.social_links).toEqual({ linkedin: "https://l.in/x" });
    expect(profileToApi({ ...profileDefaults }).social_links).toBeNull();
  });

  it("reads the API values back, tolerating missing ones", () => {
    const v = profileFromApi({ tax_number: "N", social_links: { github: "g" } });
    expect(v.tax_number).toBe("N");
    expect(v.social_links?.github).toBe("g");
    expect(v.visa_number).toBe("");
    expect(profileFromApi({}).social_links?.linkedin).toBe("");
  });
});

describe("form fields", () => {
  it("lets you type the new numbers and details", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByLabelText("Tax Number (NTN / TIN)"), "NTN-5");
    await user.type(screen.getByLabelText("EOBI / Social Security No."), "E-1");
    await user.type(screen.getByLabelText("LinkedIn"), "https://l.in/me");
    const v = latest();
    expect(v.tax_number).toBe("NTN-5");
    expect(v.social_security_number).toBe("E-1");
    expect(v.social_links?.linkedin).toBe("https://l.in/me");
  });
});
