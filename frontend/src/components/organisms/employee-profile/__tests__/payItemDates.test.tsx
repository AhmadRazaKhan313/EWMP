/**
 * E-04: pay items can be recurring or one-time and carry effective dates.
 *
 * Run:  cd frontend && npm test -- payItemDates
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FormProvider, useForm } from "react-hook-form";
import { PayItemsSection } from "../sections";
import {
  newPayItem, previewTotals, profileDefaults, profileFromApi, profileToApi, validateProfile,
  type ProfileFormValues,
} from "../profileForm";

let latest: () => ProfileFormValues;
function Harness({ items }: { items: ProfileFormValues["compensation_items"] }) {
  const form = useForm<ProfileFormValues>({ defaultValues: { ...profileDefaults, compensation_items: items } });
  latest = () => form.getValues();
  return <FormProvider {...form}><PayItemsSection currency="PKR" basic={100000} /></FormProvider>;
}
const item = (over: Partial<ProfileFormValues["compensation_items"][number]> = {}) =>
  ({ ...newPayItem("earning", "Medical"), amount: "5000", ...over });
const profile = (items: ProfileFormValues["compensation_items"]) => ({ ...profileDefaults, compensation_items: items });

describe("mapping", () => {
  it("sends dates, and drops the end date of a one-time item", () => {
    const out = profileToApi(profile([
      item({ effective_from: "2026-07-01", effective_to: "2026-12-31" }),
      item({ name: "Bonus", frequency: "one_time", effective_from: "2026-06-15", effective_to: "2026-09-01" }),
    ]));
    expect(out.compensation_items[0]).toMatchObject({ frequency: "recurring", effective_from: "2026-07-01", effective_to: "2026-12-31" });
    expect(out.compensation_items[1]).toMatchObject({ frequency: "one_time", effective_from: "2026-06-15", effective_to: null });
  });

  it("reads saved items back and treats old rows (no dates) as recurring and open-ended", () => {
    const v = profileFromApi({ compensation_items: [
      { id: "a", name: "Old", kind: "earning", amount: "10" },
      { id: "b", name: "Bonus", kind: "earning", amount: "10", frequency: "one_time", effective_from: "2026-06-15" },
    ] });
    expect(v.compensation_items[0]).toMatchObject({ frequency: "recurring", effective_from: "", effective_to: "" });
    expect(v.compensation_items[1]).toMatchObject({ frequency: "one_time", effective_from: "2026-06-15" });
  });
});

describe("validation", () => {
  it("needs a date for a one-time item and a sensible range for a recurring one", () => {
    expect(validateProfile(profile([item({ frequency: "one_time" })] ) as ProfileFormValues)?.message).toMatch(/one-time/);
    expect(validateProfile(profile([item({ effective_from: "2026-07-01", effective_to: "2026-06-01" })]))?.message).toMatch(/end date/);
    expect(validateProfile(profile([item({ effective_from: "2026-07-01", effective_to: "2026-07-01" })]))).toBeNull();
    expect(validateProfile(profile([item({ frequency: "one_time", effective_from: "2026-07-01" })]))).toBeNull();
  });
});

describe("monthly preview", () => {
  it("leaves one-time items out of a regular month", () => {
    const t = previewTotals(100000, [item(), item({ name: "Bonus", amount: "20000", frequency: "one_time", effective_from: "2026-06-01" })]);
    expect(t.allowances).toBe(5000);
  });
});

describe("form", () => {
  it("shows the date boxes, and a one-time item hides 'effective to'", async () => {
    const user = userEvent.setup();
    render(<Harness items={[item()]} />);
    await user.type(screen.getByLabelText("Pay item 1 effective from"), "2026-07-01");
    await user.type(screen.getByLabelText("Pay item 1 effective to"), "2026-12-31");
    expect(latest().compensation_items[0]).toMatchObject({ effective_from: "2026-07-01", effective_to: "2026-12-31" });
    await user.selectOptions(screen.getByLabelText("Pay item 1 frequency"), "one_time");
    expect(screen.queryByLabelText("Pay item 1 effective to")).toBeNull();
    expect(screen.getByText("Applies on")).toBeTruthy();
  });
});
