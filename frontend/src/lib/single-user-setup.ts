import { createHash, timingSafeEqual } from "node:crypto";

/** Server-only validation; the initial token must never enter a NEXT_PUBLIC variable. */
export function singleUserSetupEnabled(env: Record<string, string | undefined> = process.env): boolean {
  return env.SELF_HOST_SINGLE_USER === "true" && env.NEXT_PUBLIC_SELF_HOST !== "false";
}

export function validInitialSetupToken(provided: string | null | undefined, expected: string | undefined): boolean {
  if (!expected || expected.length < 32 || !provided || provided.length > 1024) return false;
  const digest = (value: string) => createHash("sha256").update(value).digest();
  return timingSafeEqual(digest(provided), digest(expected));
}
