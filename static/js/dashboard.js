(() => {
  const token = document.body.dataset.token;
  const settlementEl = document.getElementById("settlement-list");
  const billsEl = document.getElementById("bills-list");
  const summaryLine = document.getElementById("summary-line");
  const groupNameEl = document.getElementById("group-name");
  const pinInput = document.getElementById("edit-pin");
  const toastEl = document.getElementById("toast");

  function toast(msg) {
    toastEl.hidden = false;
    toastEl.textContent = msg;
    clearTimeout(toastEl._t);
    toastEl._t = setTimeout(() => {
      toastEl.hidden = true;
    }, 2600);
  }

  async function getJson(url, options) {
    const res = await fetch(url, options);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || res.statusText);
    return data;
  }

  function money(v) {
    const n = Number(v);
    return Number.isFinite(n) ? `$${n % 1 === 0 ? n.toFixed(0) : n.toFixed(2)}` : `$${v}`;
  }

  function renderSettlement(data) {
    if (!data.edges || data.edges.length === 0) {
      settlementEl.innerHTML = `<p class="empty">🎉 目前沒有需要轉移的淨欠款。</p>`;
      return;
    }
    settlementEl.innerHTML = data.edges
      .map(
        (e) => `
      <div class="edge">
        <div>
          <strong>@${e.from}</strong> → <strong>@${e.to}</strong>
          <div class="meta">抵消後應付</div>
        </div>
        <div class="amount">${money(e.amount)}</div>
      </div>`
      )
      .join("");
  }

  function renderBills(bills) {
    if (!bills.length) {
      billsEl.innerHTML = `<p class="empty">尚無帳單。在 LINE 用 #新增支出 記一筆吧。</p>`;
      return;
    }
    billsEl.innerHTML = bills
      .map((b) => {
        const status = b.is_archived
          ? `<span class="pill ok">已封存</span>`
          : b.unpaid_count > 0
            ? `<span class="pill warn">未結清 ${b.unpaid_count}</span>`
            : `<span class="pill ok">已結清</span>`;
        const people = (b.participants || [])
          .map((p) => {
            const paidLabel = p.is_paid ? "已付" : "未付";
            const btn =
              !p.is_paid && !b.is_archived
                ? `<button type="button" class="settle-btn" data-bill="${b.id}" data-name="${encodeURIComponent(p.name)}">標記已付</button>`
                : "";
            return `<li>
              <span>@${p.name} · ${paidLabel} · ${money(p.amount)}</span>
              <span>${btn}</span>
            </li>`;
          })
          .join("");
        return `
          <article class="card-row">
            <div class="title">
              <span>B-${b.id} ${b.description}</span>
              <span>${money(b.total_amount)}</span>
            </div>
            <div class="meta">付款人 @${b.payer || "?"} · ${b.split_type_label || ""} · ${status}</div>
            <ul class="participants">${people}</ul>
          </article>`;
      })
      .join("");

    billsEl.querySelectorAll(".settle-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const pin = pinInput.value.trim();
        if (!pin) {
          toast("請先輸入編輯 PIN");
          pinInput.focus();
          return;
        }
        btn.disabled = true;
        try {
          await getJson(`/api/v1/groups/${token}/bills/${btn.dataset.bill}/settle`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              edit_pin: pin,
              debtor_names: [decodeURIComponent(btn.dataset.name)],
            }),
          });
          toast(`已標記 @${decodeURIComponent(btn.dataset.name)} 已付`);
          await loadAll();
        } catch (err) {
          toast(err.message || "結帳失敗");
          btn.disabled = false;
        }
      });
    });
  }

  async function loadAll() {
    const [summary, settlement, bills] = await Promise.all([
      getJson(`/api/v1/groups/${token}/summary`),
      getJson(`/api/v1/groups/${token}/settlement`),
      getJson(`/api/v1/groups/${token}/bills`),
    ]);
    if (summary.group?.name) groupNameEl.textContent = summary.group.name;
    const s = summary.summary || {};
    summaryLine.textContent = `共 ${s.bill_count || 0} 筆帳單 · 未結清 ${s.unpaid_amount || 0} · 總支出 ${s.total_spend || 0}`;
    renderSettlement(settlement);
    renderBills(bills.bills || []);
  }

  document.getElementById("btn-refresh")?.addEventListener("click", () => {
    loadAll().catch((e) => toast(e.message));
  });

  loadAll().catch((e) => {
    summaryLine.textContent = e.message;
    toast(e.message);
  });
})();
