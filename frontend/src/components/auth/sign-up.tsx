"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { signUp } from "../../lib/auth-client";
import { trackEvent } from "@/lib/analytics";
import { attributionMetadata, getAnonymousAttribution } from "@/lib/attribution";
import { postAuthPath } from "@/lib/auth-redirect";
import { track } from "@/lib/datafast";
import { Button } from "../ui/button";
import { Input } from "../ui/input";

export function SignUp({ singleUserSetup = false }: { singleUserSetup?: boolean }) {
  const t = useTranslations("auth");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [setupToken, setSetupToken] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [ok, setOk] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setMessage("");
    setOk(false);

    const response = await signUp.email({
      email,
      password,
      name,
      ...(singleUserSetup ? { fetchOptions: { headers: { "x-supoclip-setup-token": setupToken.trim() } } } : {}),
    }).catch(() => null);

    if (!response) {
      setMessage(t("signUp.failed"));
      setLoading(false);
      return;
    }

    if (response.error) {
      setMessage(response.error.message || t("signUp.failed"));
      setLoading(false);
      return;
    }

    track("signup_completed", {
      auth_method: "email",
      ...attributionMetadata(getAnonymousAttribution()),
    });
    trackEvent("signup_completed", { method: "email" });
    setOk(true);
    setSetupToken("");
    setMessage(t("signUp.success"));
    setLoading(false);

    // Automatically sign in after successful sign up
    setTimeout(() => {
      window.location.href = singleUserSetup ? "/recording" : postAuthPath(window.location.search);
    }, 1000);
  };

  return (
    <div className="w-full">
      <h1 className="font-display text-3xl font-bold tracking-tight">{singleUserSetup ? "Set up your studio" : t("signUp.title")}</h1>
      <p className="mt-2 text-sm text-muted-foreground">{singleUserSetup ? "Create the owner account for this server. Use the setup token printed by the installer." : t("signUp.subtitle")}</p>
      <div className="mt-8">
        <form onSubmit={handleSubmit} className="space-y-4">
          <Input
            className="h-11"
            type="text"
            placeholder={t("signUp.name")}
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            disabled={loading}
          />
          <Input
            className="h-11"
            type="email"
            placeholder={t("signUp.email")}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            disabled={loading}
          />
          <Input
            className="h-11"
            type="password"
            placeholder={t("signUp.password")}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            disabled={loading}
            minLength={8}
          />
          {singleUserSetup && <div className="space-y-1.5"><label htmlFor="setup-token" className="text-sm font-medium">Setup token</label><Input id="setup-token" className="h-11" type="password" value={setupToken} onChange={(event) => setSetupToken(event.target.value)} required disabled={loading} autoComplete="off" spellCheck={false} /><p className="text-xs text-muted-foreground">This token is used only to create the first owner account.</p></div>}
          <Button type="submit" className="h-11 w-full" disabled={loading}>
            {loading ? t("signUp.submitting") : singleUserSetup ? "Create owner account" : t("signUp.submit")}
          </Button>
        </form>
        {message && (
          <p className={`mt-4 text-sm ${ok ? "text-green-600" : "text-red-600"}`}>
            {message}
          </p>
        )}
      </div>
    </div>
  );
}
