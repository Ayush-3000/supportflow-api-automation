"use strict";
let tickets = [],
  selectedId = null,
  mode = "demo";
const $ = (id) => document.getElementById(id);
const labels = {
  processing: "Processing",
  pending_review: "Awaiting review",
  escalated: "Escalated",
  failed: "API failure",
  sending: "Delivering",
  sent: "Delivered",
  delivery_unknown: "Delivery uncertain",
};
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        char
      ],
  );
const pill = (status) =>
  `<span class="pill ${esc(status)}">${esc(labels[status] || status)}</span>`;
function toast(message) {
  $("toast").textContent = message;
  $("toast").hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => ($("toast").hidden = true), 6000);
}
async function api(path, options = {}) {
  const result = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": $("api-key").value,
      ...options.headers,
    },
  });
  const body = await result.json();
  if (!result.ok)
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : "Check the entered values and try again.",
    );
  return body;
}
async function refresh() {
  try {
    const data = await api("/api/tickets");
    tickets = data.tickets;
    mode = data.mode;
    render();
  } catch (error) {
    toast(error.message);
  }
}
function render() {
  for (const [id, status] of [
    ["stat-review", "pending_review"],
    ["stat-escalated", "escalated"],
    ["stat-sent", "sent"],
    ["stat-failed", "failed"],
  ])
    $(id).textContent = tickets.filter((t) => t.status === status).length;
  $("total-count").textContent = tickets.length;
  $("nav-count").textContent = tickets.filter(
    (t) => t.status === "pending_review",
  ).length;
  const shown = tickets.filter(
    (t) => $("filter").value === "all" || t.status === $("filter").value,
  );
  if (!shown.some((t) => t.id === selectedId))
    selectedId = shown[0]?.id ?? null;
  $("ticket-list").innerHTML = shown.length
    ? shown
        .map(
          (t) =>
            `<button class="ticket-row ${t.id === selectedId ? "selected" : ""}" data-ticket="${esc(t.id)}" type="button"><div class="ticket-topline"><span class="ticket-code">${esc(t.event.ticket_id.toUpperCase())}</span>${pill(t.status)}</div><strong>${esc(t.event.subject)}</strong><small>${esc(t.event.customer_email)}</small></button>`,
        )
        .join("")
    : '<div class="empty"><p>No tickets here yet. Try a demo scenario above.</p></div>';
  document.querySelectorAll("[data-ticket]").forEach((button) =>
    button.addEventListener("click", () => {
      selectedId = button.dataset.ticket;
      render();
    }),
  );
  const ticket = tickets.find((t) => t.id === selectedId);
  if (ticket) renderDetail(ticket);
  else
    $("detail").innerHTML =
      '<div class="empty"><div class="empty-mark">◇</div><h3>Your review workspace is ready</h3><p>Run a demo scenario to inspect the API evidence, draft, and decision history.</p></div>';
}
function renderDetail(t) {
  const sourceHtml = t.sources
    .map((s) => {
      const facts = s.id === "order-api" ? t.facts : null;
      const text = facts
        ? `Order ${facts.order_number} · ${facts.fulfillment_status.replaceAll("_", " ").toLowerCase()}\n${facts.tracking.map((item) => `${item.company || "Carrier"}: ${item.number || "Tracking not available"}`).join("\n") || "No tracking number available yet."}`
        : s.text;
      return `<div class="source"><strong>${esc(s.title)}</strong><p>${esc(text)}</p></div>`;
    })
    .join("");
  const state = `<div class="state-note ${esc(t.status)}">${esc(t.reason)}</div>`;
  $("detail").innerHTML =
    `<div class="detail-head"><div><h3>${esc(t.event.subject)}</h3><small>${esc(t.event.customer_email)} · ${esc(t.category.replaceAll("_", " "))}</small></div>${pill(t.status)}</div><div class="detail-body"><p class="section-label">CUSTOMER REQUEST</p><div class="customer-message">${esc(t.event.message)}</div>${sourceHtml ? `<p class="section-label">VERIFIED SOURCES</p>${sourceHtml}` : ""}${t.draft ? `<div class="draft-header"><p class="section-label">${t.status === "sent" ? "APPROVED REPLY" : "RESPONSE DRAFT"}</p><small>${t.provider === "openai" ? "AI-generated · verify facts" : "Approved template · no model call"}</small></div><label for="reply" class="sr-only">Review and edit reply</label><textarea id="reply" ${t.status !== "pending_review" ? "readonly" : ""}>${esc(t.approved_reply || t.draft)}</textarea><p class="review-note">${t.status === "pending_review" ? "Edit the reply if needed. Nothing is delivered until you approve." : esc(t.reason)}</p>` : `<p class="section-label">WORKFLOW DECISION</p>${state}`}<div class="action-row">${t.status === "pending_review" ? `<button id="approve" class="primary-button" type="button">Approve & deliver${mode === "demo" ? " to demo helpdesk" : ""} <span aria-hidden="true">&nbsp; →</span></button><small>Revision ${t.revision} · Review required</small>` : t.status === "failed" ? '<button id="retry" class="quiet-button" type="button">Retry order lookup</button><small>Retries only the read workflow.</small>' : t.status === "delivery_unknown" ? "<small>Check the helpdesk receipt. Automatic resend is disabled.</small>" : t.status === "sent" ? `<small>Receipt: ${esc(t.receipt_id)} · Reviewer: ${esc(t.reviewer)}</small>` : "<small>Requires a support specialist to handle this ticket.</small>"}</div><details class="audit" open><summary>Activity & audit trail · ${t.audit.length} events</summary><ol>${t.audit.map((a) => `<li><strong>${esc(a.action.replaceAll("_", " "))}</strong>${esc(a.detail)}<small>${esc(new Date(a.at).toLocaleTimeString())}</small></li>`).join("")}</ol></details></div>`;
  if ($("approve"))
    $("approve").addEventListener("click", () => {
      if (!$("reply").value.trim())
        return toast("Enter a reply before approving.");
      $("confirm-description").textContent =
        mode === "demo"
          ? "This sends your edited reply to the local fictional helpdesk only. The decision and receipt will be recorded."
          : "This sends your edited reply to the configured helpdesk. Confirm the customer, evidence, and wording before continuing.";
      $("approval-dialog").showModal();
    });
  if ($("retry"))
    $("retry").addEventListener("click", async () => {
      $("retry").disabled = true;
      try {
        await api(`/api/tickets/${t.id}/retry`, { method: "POST" });
        await refresh();
        toast("Read workflow retried.");
      } catch (error) {
        toast(error.message);
        await refresh();
      }
    });
}
$("confirm-approval").addEventListener("click", async () => {
  const t = tickets.find((ticket) => ticket.id === selectedId);
  if (!t || !$("reviewer").value.trim())
    return toast("Enter the reviewer name.");
  const button = $("confirm-approval");
  button.disabled = true;
  try {
    const result = await api(`/api/tickets/${t.id}/approve`, {
      method: "POST",
      body: JSON.stringify({
        revision: t.revision,
        reviewer: $("reviewer").value.trim(),
        reply: $("reply").value.trim(),
      }),
    });
    $("approval-dialog").close();
    await refresh();
    toast(
      result.status === "sent"
        ? "Reviewed reply delivered. Receipt saved."
        : "Delivery is uncertain. Check the helpdesk before another send.",
    );
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
  }
});
$("filter").addEventListener("change", render);
$("refresh").addEventListener("click", refresh);
$("connect").addEventListener("click", async () => {
  sessionStorage.setItem("supportflow-key", $("api-key").value);
  await refresh();
  await scenarios();
});
async function scenarios() {
  if (mode !== "demo") {
    $("scenarios").hidden = true;
    return;
  }
  try {
    const list = await api("/api/demo/scenarios");
    $("scenario-buttons").innerHTML = list
      .map(
        (s) =>
          `<button type="button" data-scenario="${esc(s.id)}" title="${esc(s.description)}">${esc(s.label)}</button>`,
      )
      .join("");
    document.querySelectorAll("[data-scenario]").forEach((button) =>
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          const ticket = await api(
            `/api/demo/scenarios/${button.dataset.scenario}`,
            { method: "POST" },
          );
          selectedId = ticket.id;
          $("filter").value = "all";
          await refresh();
          toast("Demo ticket processed. Inspect its evidence and decision.");
        } catch (error) {
          toast(error.message);
        } finally {
          button.disabled = false;
        }
      }),
    );
  } catch (error) {
    toast(error.message);
  }
}
async function start() {
  try {
    const health = await (await fetch("/health")).json();
    mode = health.mode;
    $("mode-badge").textContent =
      mode === "demo" ? "LOCAL DEMO" : "LIVE CONNECTIONS";
    $("api-key").value =
      sessionStorage.getItem("supportflow-key") ||
      (mode === "demo" ? "demo-local-key" : "");
    if (mode !== "demo") {
      $("notice").querySelector("strong").textContent = "Live API workspace";
      $("notice").querySelector("div span").textContent =
        "Replies are delivered only after explicit human approval. Review every source and customer match.";
      $("reviewer").value = "";
    } else if (health.drafter === "openai") {
      $("notice").querySelector("div span").textContent =
        "Fictional orders and local delivery. AI drafting enabled; model calls use your configured OpenAI account.";
    }
    await refresh();
    await scenarios();
  } catch (error) {
    toast("Workspace unavailable. Check that the local API is running.");
  }
}
start();
