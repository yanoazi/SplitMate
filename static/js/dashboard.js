(() => {
  const token = document.body.dataset.token;
  const settlementEl = document.getElementById("settlement-list");
  const batchEl = document.getElementById("batch-settlement-list");
  const billsEl = document.getElementById("bills-list");
  const summaryLine = document.getElementById("summary-line");
  const groupNameEl = document.getElementById("group-name");
  const pinInput = document.getElementById("edit-pin");
  const toastEl = document.getElementById("toast");

  function toast(msg) {
    toastEl.hidden = false;
    toastEl.textContent = msg;
    if (typeof gsap !== "undefined") {
      gsap.fromTo(
        toastEl,
        { y: 16, autoAlpha: 0 },
        { y: 0, autoAlpha: 1, duration: 0.35, ease: "power2.out" }
      );
    }
    clearTimeout(toastEl._t);
    toastEl._t = setTimeout(() => {
      toastEl.hidden = true;
    }, 2800);
  }

  function requirePin() {
    const pin = pinInput.value.trim();
    if (!pin) {
      toast("請先輸入 PIN（LINE 打 #網頁）");
      pinInput.focus();
      return null;
    }
    return pin;
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

  function renderEdges(target, data, emptyText) {
    if (!data.edges || data.edges.length === 0) {
      target.innerHTML = `<p class="empty">${emptyText}</p>`;
      return;
    }
    const head = `<p class="meta">最少 ${data.transfer_count ?? data.edges.length} 筆轉帳 · 未付合計 ${money(data.total_outstanding)}${
      data.matched_bill_ids?.length ? ` · B-${data.matched_bill_ids.join("、B-")}` : ""
    }</p>`;
    target.innerHTML =
      head +
      data.edges
        .map(
          (e) => `
      <div class="edge">
        <div>
          <strong>@${e.from}</strong> → <strong>@${e.to}</strong>
          <div class="meta">應付</div>
        </div>
        <div class="amount">${money(e.amount)}</div>
      </div>`
        )
        .join("");

    if (typeof gsap !== "undefined") {
      gsap.from(target.querySelectorAll(".edge"), {
        y: 18,
        autoAlpha: 0,
        duration: 0.45,
        stagger: 0.06,
        ease: "power2.out",
      });
    }
  }

  function selectedBillIds() {
    return [...billsEl.querySelectorAll(".bill-check:checked")].map((el) =>
      Number(el.value)
    );
  }

  function renderBills(bills) {
    if (!bills.length) {
      billsEl.innerHTML = `<p class="empty">尚無帳單。在 LINE 由付款人用 #分帳 記一筆。</p>`;
      return;
    }
    billsEl.innerHTML = bills
      .map((b) => {
        const status = b.is_archived
          ? `<span class="pill ok">已封存</span>`
          : b.unpaid_count > 0
            ? `<span class="pill warn">未結清 ${b.unpaid_count}</span>`
            : `<span class="pill ok">已結清</span>`;
        const canSelect = !b.is_archived && b.unpaid_count > 0;
        const check = canSelect
          ? `<label class="check-wrap"><input type="checkbox" class="bill-check" value="${b.id}" /> 納入批次</label>`
          : `<span class="meta">—</span>`;
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
          <article class="bill-row">
            <div class="title">
              <span>B-${b.id} ${b.description}</span>
              <span>${money(b.total_amount)}</span>
            </div>
            <div class="meta">付款人 @${b.payer || "?"} · ${b.split_type_label || ""} · ${status}</div>
            <div class="row-actions">
              ${check}
              <button type="button" class="delete-btn" data-bill="${b.id}" data-desc="${encodeURIComponent(b.description)}">刪除</button>
            </div>
            <ul class="participants">${people}</ul>
          </article>`;
      })
      .join("");

    if (typeof gsap !== "undefined") {
      gsap.from(billsEl.querySelectorAll(".bill-row"), {
        y: 14,
        autoAlpha: 0,
        duration: 0.4,
        stagger: 0.05,
        ease: "power2.out",
      });
    }

    billsEl.querySelectorAll(".settle-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const pin = requirePin();
        if (!pin) return;
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

    billsEl.querySelectorAll(".delete-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const pin = requirePin();
        if (!pin) return;
        const desc = decodeURIComponent(btn.dataset.desc || "");
        if (!confirm(`確定刪除 B-${btn.dataset.bill} ${desc}？`)) return;
        btn.disabled = true;
        try {
          await getJson(`/api/v1/groups/${token}/bills/${btn.dataset.bill}`, {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ edit_pin: pin }),
          });
          toast(`已刪除 B-${btn.dataset.bill}`);
          await loadAll();
        } catch (err) {
          toast(err.message || "刪除失敗");
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
    summaryLine.textContent = `共 ${s.bill_count || 0} 筆 · 未結清 ${s.unpaid_amount || 0} · 總支出 ${s.total_spend || 0}`;
    renderEdges(settlementEl, settlement, "目前沒有需要轉帳的淨欠款。");
    renderBills(bills.bills || []);
    batchEl.innerHTML = `<p class="empty">勾選帳單後按「計算相抵」。</p>`;
  }

  document.getElementById("btn-refresh")?.addEventListener("click", () => {
    loadAll().catch((e) => toast(e.message));
  });

  document.getElementById("btn-select-unpaid")?.addEventListener("click", () => {
    billsEl.querySelectorAll(".bill-check").forEach((el) => {
      el.checked = true;
    });
    toast("已勾選全部未結清");
  });

  document.getElementById("btn-clear-select")?.addEventListener("click", () => {
    billsEl.querySelectorAll(".bill-check").forEach((el) => {
      el.checked = false;
    });
    batchEl.innerHTML = `<p class="empty">已清除勾選。</p>`;
  });

  document.getElementById("btn-batch-calc")?.addEventListener("click", async () => {
    const bill_ids = selectedBillIds();
    if (!bill_ids.length) {
      toast("請先勾選至少一筆");
      return;
    }
    try {
      const data = await getJson(`/api/v1/groups/${token}/settlement/batch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bill_ids }),
      });
      renderEdges(batchEl, data, "勾選帳單抵消後已結清。");
      toast(`已計算 ${bill_ids.length} 筆相抵`);
    } catch (err) {
      toast(err.message || "計算失敗");
    }
  });

  document.getElementById("btn-batch-settle")?.addEventListener("click", async () => {
    const pin = requirePin();
    if (!pin) return;
    const bill_ids = selectedBillIds();
    if (!bill_ids.length) {
      toast("請先勾選至少一筆");
      return;
    }
    if (!confirm(`確定將勾選的 ${bill_ids.length} 筆全部標記已付？`)) return;
    try {
      const data = await getJson(`/api/v1/groups/${token}/bills/settle-batch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ edit_pin: pin, bill_ids }),
      });
      toast(`已結清 ${data.result?.settled_bill_ids?.length || 0} 筆`);
      await loadAll();
    } catch (err) {
      toast(err.message || "批次結清失敗");
    }
  });

  loadAll().catch((e) => {
    summaryLine.textContent = e.message;
    toast(e.message);
  });
})();
