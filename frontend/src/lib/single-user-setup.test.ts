import { describe, expect, it } from "vitest";
import { singleUserSetupEnabled, validInitialSetupToken } from "./single-user-setup";

describe("single-operator setup", () => {
  const token = "a".repeat(64);
  it("requires an explicitly enabled self-hosted installation", () => {
    expect(singleUserSetupEnabled({})).toBe(false);
    expect(singleUserSetupEnabled({ SELF_HOST_SINGLE_USER: "true", NEXT_PUBLIC_SELF_HOST: "true" })).toBe(true);
    expect(singleUserSetupEnabled({ SELF_HOST_SINGLE_USER: "true", NEXT_PUBLIC_SELF_HOST: "false" })).toBe(false);
  });
  it("accepts only the exact server-held initial token", () => {
    expect(validInitialSetupToken(token, token)).toBe(true);
    expect(validInitialSetupToken("b" + token.slice(1), token)).toBe(false);
    expect(validInitialSetupToken(token.slice(1), token)).toBe(false);
    expect(validInitialSetupToken(` ${token}`, token)).toBe(false);
  });
  it("fails closed with missing, weak, or oversized tokens", () => {
    expect(validInitialSetupToken(undefined, token)).toBe(false);
    expect(validInitialSetupToken(token, undefined)).toBe(false);
    expect(validInitialSetupToken("short", "short")).toBe(false);
    expect(validInitialSetupToken("a".repeat(1025), token)).toBe(false);
  });
});
