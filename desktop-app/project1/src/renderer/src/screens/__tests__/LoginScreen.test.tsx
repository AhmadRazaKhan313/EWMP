import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LoginScreen from "../LoginScreen";
import { useAuthStore } from "../../store/authStore";

describe("LoginScreen", () => {
  beforeEach(() => {
    useAuthStore.setState({ status: "unauthenticated", user: null, error: null });
  });

  it("submits email and password to the auth store's login action", async () => {
    const loginSpy = vi.fn().mockResolvedValue(undefined);
    useAuthStore.setState({ login: loginSpy });

    render(<LoginScreen />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/email/i), "a@b.com");
    await user.type(screen.getByLabelText(/password/i), "secret123");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(loginSpy).toHaveBeenCalledWith("a@b.com", "secret123"));
  });

  it("shows the store's error message after a failed login", async () => {
    useAuthStore.setState({ error: "Invalid credentials" });
    render(<LoginScreen />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid credentials");
  });

  it("requires both fields before the browser allows submission", () => {
    render(<LoginScreen />);
    expect(screen.getByLabelText(/email/i)).toBeRequired();
    expect(screen.getByLabelText(/password/i)).toBeRequired();
  });
});
