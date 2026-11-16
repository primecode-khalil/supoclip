import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { SignUp } from "./sign-up";
import { signUp } from "../../lib/auth-client";

vi.mock("../../lib/auth-client", () => ({
  signUp: {
    email: vi.fn(),
  },
}));

describe("SignUp", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders API errors", async () => {
    vi.mocked(signUp.email).mockResolvedValue({
      error: { message: "Account already exists" },
    } as never);
    const user = userEvent.setup();

    render(<SignUp />);

    await user.type(screen.getByPlaceholderText("Full Name"), "Jane Admin");
    await user.type(screen.getByPlaceholderText("Email"), "admin@example.com");
    await user.type(screen.getByPlaceholderText("Password"), "Password123!");
    await user.click(screen.getByRole("button", { name: "Sign Up" }));

    expect(await screen.findByText("Account already exists")).toBeInTheDocument();
  });

  it("requires the private setup token for single-user setup and forwards it only as a header", async () => {
    vi.mocked(signUp.email).mockResolvedValue({ error: { message: "Invalid setup token" } } as never);
    const user = userEvent.setup();
    render(<SignUp singleUserSetup />);
    await user.type(screen.getByPlaceholderText("Full Name"), "VPS Owner");
    await user.type(screen.getByPlaceholderText("Email"), "owner@example.com");
    await user.type(screen.getByPlaceholderText("Password"), "Password123!");
    const token = screen.getByLabelText("Setup token");
    expect(token).toHaveAttribute("type", "password");
    expect(token).toBeRequired();
    await user.type(token, "demo-local-install-token");
    await user.click(screen.getByRole("button", { name: "Create owner account" }));
    expect(signUp.email).toHaveBeenCalledWith(expect.objectContaining({ fetchOptions: { headers: { "x-supoclip-setup-token": "demo-local-install-token" } } }));
    expect(vi.mocked(signUp.email).mock.calls[0][0]).not.toHaveProperty("setupToken");
  });

  it("shows a success state after sign up", async () => {
    vi.mocked(signUp.email).mockResolvedValue({ error: null } as never);
    const user = userEvent.setup();

    render(<SignUp />);

    await user.type(screen.getByPlaceholderText("Full Name"), "Jane Admin");
    await user.type(screen.getByPlaceholderText("Email"), "admin@example.com");
    await user.type(screen.getByPlaceholderText("Password"), "Password123!");
    await user.click(screen.getByRole("button", { name: "Sign Up" }));

    expect(
      await screen.findByText("Account created successfully! Signing you in..."),
    ).toBeInTheDocument();
  });
});
