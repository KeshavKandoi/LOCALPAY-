"use client";

import Link from "next/link";
import { useState } from "react";
import { ActionForm, Panel } from "./panels";
import { BrandIcon } from "@/lib/sections";
import { Button } from "./ui/button";

function PasswordField({ label, name, current = false }: { label: string; name: string; current?: boolean }) {
  const [visible, setVisible] = useState(false);
  return <div>
    <label>{label}<input name={name} type={visible ? "text" : "password"} autoComplete={current ? "current-password" : "new-password"} minLength={current ? undefined : 12} maxLength={128} required /></label>
    <Button type="button" variant="ghost" aria-pressed={visible} aria-label={(visible ? "Hide " : "Show ") + label.toLowerCase()} onClick={() => setVisible(!visible)}>{visible ? "Hide password" : "Show password"}</Button>
  </div>;
}

async function accountAction(method: string, action: string, fields?: FormData) {
  const response = await fetch("/api/session" + (action ? "?action=" + action : ""), {
    method, headers: { "Content-Type": "application/json" }, body: fields ? JSON.stringify(Object.fromEntries(fields)) : undefined,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error ?? "Account service unavailable.");
  return data as { username: string };
}

export function AccountLogin({ signup, dark, toggleTheme, signedIn }: { signup: boolean; dark: boolean; toggleTheme: () => void; signedIn: (username: string) => void }) {
  return <main className="login" data-theme={dark ? "dark" : "light"}><div className="login-card panel">
    <div className="brand"><span className="brand-icon"><BrandIcon size={20} aria-hidden /></span>LocalPay</div>
    <h1>{signup ? "Create a LocalPay account" : "Sign in to LocalPay"}</h1>
    {signup && <p>Use 3–32 letters, numbers, underscores or hyphens for your username. Choose a password of at least 12 characters.</p>}
    <ActionForm key={String(signup)} label={signup ? "Sign up" : "Sign in"} execute={async (fields) => {
      signedIn((await accountAction("POST", signup ? "signup" : "", fields)).username);
      return "Signed in.";
    }}>
      <label>Username<input name="username" autoComplete="username" required minLength={signup ? 3 : undefined} maxLength={32} /></label>
      <PasswordField label="Password" name="password" current={!signup} />
      {signup && <PasswordField label="Confirm password" name="confirm_password" />}
    </ActionForm>
    <div className="workspace-actions">
      <Button asChild variant="outline"><Link href={signup ? "/login" : "/signup"}>{signup ? "Sign in" : "Sign up"}</Link></Button>
      <Button variant="ghost" onClick={toggleTheme}>{dark ? "Light mode" : "Dark mode"}</Button>
    </div>
  </div></main>;
}

export function AccountSettings({ username, signOut }: { username: string; signOut: () => Promise<void> }) {
  const [version, setVersion] = useState(0);
  return <div className="section-stack">
    <h1>Account Settings</h1>
    <Panel title="Account"><div className="form-panel"><p>Username <strong>{username}</strong></p></div></Panel>
    <Panel title="Change password"><ActionForm label="Change password" execute={async (fields) => {
      await accountAction("PATCH", "", fields);
      setVersion((previous) => previous + 1);
      return "Password updated. Other sessions were signed out.";
    }}>
      <div key={version} className="section-stack">
        <PasswordField label="Current password" name="current_password" current />
        <PasswordField label="New password" name="password" />
        <PasswordField label="Confirm new password" name="confirm_password" />
      </div>
    </ActionForm></Panel>
    <Panel title="Sessions">
      <ActionForm label="Revoke other sessions" execute={async () => {
        await accountAction("DELETE", "others");
        return "Other sessions were signed out.";
      }}><span /></ActionForm>
      <ActionForm label="Sign out of this session" execute={async () => {
        await signOut();
        return "Signed out.";
      }}><span /></ActionForm>
    </Panel>
  </div>;
}
