function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

async function apiJson(url, opts = {}) {
  const res = await fetch(url, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  const text = await res.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = {};
  }
  return { ok: res.ok, status: res.status, data };
}

const els = {
  filterCandidateStatus: document.getElementById("filterCandidateStatus"),
  filterErrorType: document.getElementById("filterErrorType"),
  candidateBody: document.getElementById("candidateBody"),
  candidateEmpty: document.getElementById("candidateEmpty"),
  candidateDetail: document.getElementById("candidateDetail"),
  ruleBody: document.getElementById("ruleBody"),
  ruleEmpty: document.getElementById("ruleEmpty"),
  btnRefreshCandidates: document.getElementById("btnRefreshCandidates"),
  btnRefreshRules: document.getElementById("btnRefreshRules"),
};

function fmtUsagePrice(row, prefix) {
  const usage = row[`${prefix}_usage`] || row[`${prefix}Usage`] || "";
  const price = row[`${prefix}_unit_price`] || "";
  const amt = row[`${prefix}_amount`];
  const parts = [];
  if (usage) parts.push(`用量:${usage}`);
  if (price) parts.push(`单价:${price}`);
  if (amt != null && amt !== "") parts.push(`小计:${amt}`);
  return parts.join(" · ") || "—";
}

async function loadCandidates() {
  const status = els.filterCandidateStatus.value;
  const errorType = els.filterErrorType.value;
  const qs = new URLSearchParams();
  if (status) qs.set("status", status);
  if (errorType) qs.set("error_type", errorType);
  const { ok, data } = await apiJson(`/admin-api/quote-correction-learning/candidates?${qs.toString()}`);
  if (!ok) {
    alert(data.message || "加载候选失败");
    return;
  }
  const items = data.items || [];
  els.candidateBody.innerHTML = items
    .map((row) => {
      const cid = escapeHtml(row.candidate_id);
      const pending = String(row.status || "") === "pending";
      return `<tr data-id="${cid}">
        <td><strong>${escapeHtml(row.product_name || "—")}</strong><br/><span class="muted">${escapeHtml(row.material_name || "")}</span></td>
        <td>${escapeHtml(row.error_type || "")}</td>
        <td>${escapeHtml(fmtUsagePrice(row, "system"))}</td>
        <td>${escapeHtml(fmtUsagePrice(row, "corrected"))}</td>
        <td>${escapeHtml(row.confidence ?? "")}</td>
        <td>${escapeHtml(row.status || "")}</td>
        <td class="correction-actions">
          <button type="button" class="btn btn-ghost btn-sm" data-action="view" data-id="${cid}">详情</button>
          ${pending ? `<button type="button" class="btn btn-primary btn-sm" data-action="approve" data-id="${cid}">批准</button>
          <button type="button" class="btn btn-secondary btn-sm" data-action="reject" data-id="${cid}">驳回</button>` : ""}
        </td>
      </tr>`;
    })
    .join("");
  els.candidateEmpty.hidden = items.length > 0;
}

async function showCandidateDetail(id) {
  const { ok, data } = await apiJson(`/admin-api/quote-correction-learning/candidates/${encodeURIComponent(id)}`);
  if (!ok || !data.item) {
    alert(data.message || "加载详情失败");
    return;
  }
  const item = data.item;
  els.candidateDetail.hidden = false;
  els.candidateDetail.innerHTML = `
    <h3 class="pew-title">候选详情</h3>
    <p><strong>原因：</strong>${escapeHtml(item.reason || "")}</p>
    <p><strong>建议规则：</strong><pre class="correction-json">${escapeHtml(JSON.stringify(item.suggested_rule || item.suggested_rule_json || {}, null, 2))}</pre></p>
    <p><strong>证据：</strong><pre class="correction-json">${escapeHtml(JSON.stringify(item.evidence || item.evidence_json || {}, null, 2))}</pre></p>
  `;
}

async function approveCandidate(id) {
  const note = window.prompt("审核备注（可选）", "") || "";
  const { ok, data } = await apiJson(
    `/admin-api/quote-correction-learning/candidates/${encodeURIComponent(id)}/approve`,
    { method: "POST", body: JSON.stringify({ review_note: note, reviewed_by: "admin" }) },
  );
  if (!ok) {
    alert(data.message || "批准失败");
    return;
  }
  await loadCandidates();
  await loadRules();
}

async function rejectCandidate(id) {
  const note = window.prompt("驳回原因（建议填写）", "") || "";
  const { ok, data } = await apiJson(
    `/admin-api/quote-correction-learning/candidates/${encodeURIComponent(id)}/reject`,
    { method: "POST", body: JSON.stringify({ review_note: note, reviewed_by: "admin" }) },
  );
  if (!ok) {
    alert(data.message || "驳回失败");
    return;
  }
  await loadCandidates();
}

async function loadRules() {
  const { ok, data } = await apiJson("/admin-api/quote-correction-learning/rules?limit=200");
  if (!ok) {
    alert(data.message || "加载规则失败");
    return;
  }
  const items = data.items || [];
  els.ruleBody.innerHTML = items
    .map((row) => {
      const rid = escapeHtml(row.rule_id);
      const enabled = Number(row.enabled) === 1;
      return `<tr>
        <td>${rid}</td>
        <td>${escapeHtml(row.rule_type || "")}</td>
        <td>${escapeHtml(row.field_name || "")}</td>
        <td>${escapeHtml(row.corrected_value || "")}</td>
        <td>${escapeHtml(row.rule_status || "")}</td>
        <td>${enabled ? "是" : "否"}</td>
        <td>
          <button type="button" class="btn btn-secondary btn-sm" data-rule-toggle="${rid}" data-enabled="${enabled ? "0" : "1"}">${enabled ? "停用" : "启用"}</button>
        </td>
      </tr>`;
    })
    .join("");
  els.ruleEmpty.hidden = items.length > 0;
}

els.candidateBody.addEventListener("click", (ev) => {
  const btn = ev.target.closest("button[data-action]");
  if (!btn) return;
  const id = btn.getAttribute("data-id");
  const action = btn.getAttribute("data-action");
  if (action === "view") showCandidateDetail(id);
  if (action === "approve") approveCandidate(id);
  if (action === "reject") rejectCandidate(id);
});

els.ruleBody.addEventListener("click", async (ev) => {
  const btn = ev.target.closest("button[data-rule-toggle]");
  if (!btn) return;
  const rid = btn.getAttribute("data-rule-toggle");
  const enabled = btn.getAttribute("data-enabled") === "1";
  const { ok, data } = await apiJson(
    `/admin-api/quote-correction-learning/rules/${encodeURIComponent(rid)}/toggle`,
    { method: "POST", body: JSON.stringify({ enabled, operator: "admin" }) },
  );
  if (!ok) {
    alert(data.message || "切换失败");
    return;
  }
  await loadRules();
});

els.btnRefreshCandidates.addEventListener("click", loadCandidates);
els.btnRefreshRules.addEventListener("click", loadRules);
els.filterCandidateStatus.addEventListener("change", loadCandidates);
els.filterErrorType.addEventListener("change", loadCandidates);

loadCandidates();
loadRules();
