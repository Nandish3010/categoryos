import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ACTING_AS_STORAGE } from "@/lib/identity";
import type { PolicyResponse } from "@/lib/policy";
import type { Change, Preview } from "@/lib/rules";
import { ActingAs, resolveActing } from "./ActingAs";
import { ChangePreview } from "./ChangePreview";
import { PENDING_TOAST, RulesPage } from "./RulesPage";

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

const line = {
  keys: ["margins", "categories", "treats", "target_pct"],
  path: "margins.categories.treats.target_pct",
  label: "Category margins: treats / Target margin",
  unit: "%",
  used_in: ["research", "negotiate"],
  before: 35,
  after: 37,
};
const ready = (outcome: Preview["outcome"]): Preview => ({
  status: "ready", id: "chg_1", prompt: "Raise the target margin on treats by 2 points", translator: "recorded example", changes: [line], outcome, error: null,
});
const acting = { id: "arjun", name: "Arjun", role: "manager", role_label: "Category manager", can_apply: true, can_approve: false };

describe("ChangePreview", () => {
  const noop = () => undefined;

  it("shows label, before and after from the server and the stages that read it", () => {
    render(<ChangePreview preview={ready({ action: "apply", reason: null })} acting={acting} busy={false} onApply={noop} onDiscard={noop} />);
    expect(screen.getByText("Category margins: treats / Target margin")).toBeInTheDocument();
    expect(screen.getByLabelText("Before")).toHaveTextContent("35 %");
    expect(screen.getByLabelText("After")).toHaveTextContent("37 %");
    expect(screen.getByText("research")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Discard" })).toBeEnabled();
  });

  it("offers Request approval, with the reason, when a limit is exceeded", () => {
    const onApply = vi.fn();
    render(<ChangePreview preview={ready({ action: "request_approval", reason: "limit is 2 pp per change; this change is 5 pp" })} acting={acting} busy={false} onApply={onApply} onDiscard={noop} />);
    expect(screen.getByText(/limit is 2 pp per change/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Request approval" }));
    expect(onApply).toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Apply" })).not.toBeInTheDocument();
  });

  it("disables Request approval with the reason for an analyst", () => {
    const analyst = { ...acting, id: "priya", role: "analyst", can_apply: false };
    render(<ChangePreview preview={ready({ action: "refuse", reason: "Category analyst can write a rule but cannot apply it" })} acting={analyst} busy={false} onApply={noop} onDiscard={noop} />);
    expect(screen.getByRole("button", { name: "Request approval" })).toBeDisabled();
    expect(screen.getByText(/cannot apply it/)).toBeInTheDocument();
  });

  it("shows a validation error with cause and fix, and no buttons", () => {
    const bad: Preview = { status: "invalid", id: null, prompt: "x", translator: "model", changes: [], outcome: null, error: { code: "policy_invalid", problem: "margins.categories.treats.target_pct: Input should be at most 95", cause: "The playbook failed validation, so nothing was saved", fix: "Correct the value shown" } };
    render(<ChangePreview preview={bad} acting={acting} busy={false} onApply={noop} onDiscard={noop} />);
    expect(screen.getByText(/at most 95/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing was changed/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("says when a rule could not be mapped", () => {
    const un: Preview = { status: "unmapped", id: null, prompt: "pizza", translator: "model", changes: [], outcome: null, error: null, message: "I couldn't map this to a playbook setting." };
    render(<ChangePreview preview={un} acting={acting} busy={false} onApply={noop} onDiscard={noop} />);
    expect(screen.getByText(/couldn't map this to a playbook setting/)).toBeInTheDocument();
  });
});

const gov = {
  members: { meera: { name: "Meera", role: "head" }, arjun: { name: "Arjun", role: "manager" }, priya: { name: "Priya", role: "analyst" } },
  roles: { head: { label: "Head of category" }, manager: { label: "Category manager" }, analyst: { label: "Category analyst" } },
};

describe("ActingAs", () => {
  it("lists the team, defaults to the head, keeps the choice and says it is not a login", async () => {
    const seen: string[] = [];
    function Host() {
      return <ActingAs policy={{ governance: gov }} value={seen.at(-1) ?? null} onChange={(id) => seen.push(id)} />;
    }
    const { rerender } = render(<Host />);
    await waitFor(() => expect(seen).toEqual(["meera"]));
    expect(localStorage.getItem(ACTING_AS_STORAGE)).toBe("meera");
    rerender(<Host />);
    const select = screen.getByRole("combobox", { name: /Signed in as/ });
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["Meera, Head of category", "Arjun, Category manager", "Priya, Category analyst"]);
    expect(screen.getByText(/not a login/)).toBeInTheDocument();
    fireEvent.change(select, { target: { value: "priya" } });
    expect(localStorage.getItem(ACTING_AS_STORAGE)).toBe("priya");
    expect(seen.at(-1)).toBe("priya");
  });

  it("falls back to the head when the saved member no longer exists", () => {
    expect(resolveActing({ governance: gov }, "mallory")).toBe("meera");
    expect(resolveActing({ governance: gov }, "arjun")).toBe("arjun");
  });
});

// ---------- the page: write a rule, change log ----------

const json = (b: unknown, s = 200) => new Response(JSON.stringify(b), { status: s, headers: { "Content-Type": "application/json" } });
const policy = { research: { demand_min: 0.4 }, governance: gov, margins: { categories: { treats: { target_pct: 35 } } } };
const snap = (over: Partial<PolicyResponse> = {}): PolicyResponse => ({
  policy, defaults: structuredClone(policy), overridden_paths: [], hash: "h", editable: true, schema_hints: {}, scope: "global",
  acting: { ...acting, id: "meera", name: "Meera", role: "head", role_label: "Head of category", can_apply: true, can_approve: true }, ...over,
});
const entry = (over: Partial<Change>): Change => ({
  id: "chg_a", at: "2026-10-28T10:00:00.000+00:00", decided_at: null, actor: { id: "arjun", name: "Arjun", role: "manager" }, source: "prompt",
  prompt: "Cut the target margin on toys by 5 points", translator: "recorded example", diff: [{ ...line, label: "Toys target", before: 40, after: 35 }],
  status: "pending_approval", reason: "limit is 2 pp per change; this change is 5 pp", approver: null, hash_before: "a", hash_after: null,
  undo_of: null, undone_by: null, events: [], ...over,
});

function backend(routes: Record<string, (init?: RequestInit) => Response>) {
  const calls: { url: string; method: string; headers: Record<string, string> }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input).replace("http://localhost:8001", "");
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ url, method, headers: (init?.headers ?? {}) as Record<string, string> });
    const h = routes[`${method} ${url}`];
    return h ? h(init) : json(snap());
  }));
  return calls;
}

describe("Write a rule and the change log", () => {
  it("previews an example, applies it, and sends the acting member", async () => {
    localStorage.setItem(ACTING_AS_STORAGE, "arjun");
    const calls = backend({
      "GET /api/policy/examples": () => json({ examples: [{ prompt: "Raise the target margin on treats by 2 points", note: "Within a manager's limit" }] }),
      "POST /api/policy/propose": () => json(ready({ action: "apply", reason: null })),
      "POST /api/policy/changes/chg_1/apply": () => json(snap({ change: entry({ id: "chg_1", status: "applied" }) })),
    });
    render(<RulesPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Raise the target margin on treats by 2 points" }));
    expect(await screen.findByRole("region", { name: "Rule preview" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Rule preview" })).not.toBeInTheDocument());
    const apply = calls.find((c) => c.url.endsWith("/apply"));
    expect(apply?.headers["X-Acting-As"]).toBe("arjun");
    expect(apply?.headers["X-Visitor-Id"]).toBeTruthy();
  });

  it("shows the refusal from the server when an apply is not allowed", async () => {
    backend({
      "POST /api/policy/propose": () => json(ready({ action: "apply", reason: null })),
      "POST /api/policy/changes/chg_1/apply": () => json({ code: "change_refused", problem: "This change was refused", cause: "Category analyst can write a rule but cannot apply it", fix: "Ask someone with a higher role" }, 403),
    });
    render(<RulesPage />);
    fireEvent.change(await screen.findByRole("textbox", { name: "Describe a rule" }), { target: { value: "raise treats by 2" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview rule" }));
    fireEvent.click(await screen.findByRole("button", { name: "Apply" }));
    expect(await screen.findByText("This change was refused")).toBeInTheDocument();
    expect(screen.getByText(/cannot apply it\. Ask someone with a higher role\./)).toBeInTheDocument();
  });

  it("puts a full stop between cause and fix in the form's error banner", async () => {
    backend({ "PUT /api/policy": () => json({ code: "demo_key_required", problem: "This route needs the demo key", cause: "The X-Demo-Key header is missing or wrong", fix: "Send X-Demo-Key with the value of DEMO_KEY" }, 403) });
    render(<RulesPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Research" }));
    fireEvent.change(await screen.findByRole("spinbutton", { name: "Demand min" }), { target: { value: "0.9" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("The X-Demo-Key header is missing or wrong. Send X-Demo-Key with the value of DEMO_KEY.")).toBeInTheDocument();
  });

  it("tells a public visitor their edits are sandboxed", async () => {
    backend({ "GET /api/policy": () => json(snap({ scope: "visitor" })) });
    render(<RulesPage />);
    expect(await screen.findByText(/your changes go to your own sandbox playbook/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Research" }));
    expect(await screen.findByText(/checked against your role and logged/)).toBeInTheDocument();
  });

  it("lists the log with status chips, who, the prompt and the diff; the head can approve a request", async () => {
    let approved = false;
    backend({
      "GET /api/policy/changes": () => json({
        acting: { id: "meera", name: "Meera", role: "head" },
        changes: [
          entry({ id: "chg_a", allowed: { approve: !approved, reject: !approved, undo: false } , status: approved ? "applied" : "pending_approval" }),
          entry({ id: "chg_b", status: "applied", reason: null, prompt: "Raise the target margin on treats by 2 points", actor: { id: "meera", name: "Meera", role: "head" }, allowed: { approve: false, reject: false, undo: true } }),
          entry({ id: "chg_c", status: "refused", reason: "Category analyst can write a rule but cannot apply it", actor: { id: "priya", name: "Priya", role: "analyst" }, diff: [], allowed: { approve: false, reject: false, undo: false } }),
        ],
      }),
      "POST /api/policy/changes/chg_a/approve": () => { approved = true; return json(snap({ change: entry({ status: "applied" }) })); },
    });
    render(<RulesPage />);
    fireEvent.click(await screen.findByRole("tab", { name: "Change log" }));
    const log = await screen.findByRole("region", { name: "Change log" });
    expect(within(log).getByText("Waiting for approval")).toBeInTheDocument();
    expect(within(log).getByText("Applied")).toBeInTheDocument();
    expect(within(log).getByText("Refused")).toBeInTheDocument();
    expect(within(log).getByText("Priya")).toBeInTheDocument();
    expect(within(log).getAllByText("Cut the target margin on toys by 5 points").length).toBeGreaterThan(0);
    expect(within(log).getAllByText("Toys target").length).toBeGreaterThan(0);
    expect(within(log).getAllByRole("button", { name: "Approve" })).toHaveLength(1);
    expect(within(log).getAllByRole("button", { name: "Undo" })).toHaveLength(1);
    fireEvent.click(within(log).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(within(log).queryByRole("button", { name: "Approve" })).not.toBeInTheDocument());
  });

  it("an empty log says what gets logged", async () => {
    backend({ "GET /api/policy/changes": () => json({ acting: { id: "meera", name: "Meera", role: "head" }, changes: [] }) });
    render(<RulesPage />);
    fireEvent.click(await screen.findByRole("tab", { name: "Change log" }));
    expect(await screen.findByText(/every attempt that was refused/)).toBeInTheDocument();
  });

  it("a form save that needs approval says so", async () => {
    backend({ "PUT /api/policy": () => json(snap({ change: entry({ status: "pending_approval" }) }), 202) });
    render(<RulesPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Research" }));
    // the stub playbook has no schema hints, so the field renders by value type
    fireEvent.change(await screen.findByRole("spinbutton", { name: "Demand min" }), { target: { value: "0.9" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(PENDING_TOAST)).toBeInTheDocument();
  });
});
